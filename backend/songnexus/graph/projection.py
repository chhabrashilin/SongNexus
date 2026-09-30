"""Project stored facts into an in-memory, evidence-carrying artist graph.

Nodes are artists. An undirected edge between two artists exists when at
least one *fact* connects them, and it carries every piece of evidence:

    kind              derived from                                    weight
    ----------------  ----------------------------------------------  ------
    performed_with    both credited performers on a track/album        1.0
    produced_for      one produced a track/album the other performed   1.0
    co_produced       both produced the same track                     0.6
    contributed_to    vocal/instrument/arrangement on the other's      0.6
                      track
    sampled           the other's track samples this artist            0.4
    engineered        mix/recording/mastering on the other's track     0.25
    member_of         membership / subgroup / "is person"              3.0
    collaboration     artist is part of a collaboration project        2.0
    supported         supporting musician                              1.0
    taught            teacher relationship                             1.0

Edge *strength* = sum of weights over its evidence for the enabled kinds.
Weights are a documented heuristic (docs/graph-algorithms.md), not a claim of
optimality; they are exposed so they can be evaluated and tuned.

The graph is a read model: rebuilt from the database after ingestion, never
written back. Each projection has a ``version`` so caches keyed on it are
invalidated automatically when the graph is rebuilt.
"""

from __future__ import annotations

import itertools
import logging
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from songnexus.db import models as m

log = logging.getLogger(__name__)

KIND_WEIGHTS: dict[str, float] = {
    "performed_with": 1.0,
    "produced_for": 1.0,
    "co_produced": 0.6,
    "contributed_to": 0.6,
    "sampled": 0.4,
    "engineered": 0.25,
    "member_of": 3.0,
    "collaboration": 2.0,
    "supported": 1.0,
    "taught": 1.0,
}

# User-facing filter groups -> evidence kinds.
CATEGORIES: dict[str, frozenset[str]] = {
    "performance": frozenset({"performed_with"}),
    "production": frozenset({"produced_for", "co_produced"}),
    "contribution": frozenset({"contributed_to"}),
    "sampling": frozenset({"sampled"}),
    "engineering": frozenset({"engineered"}),
    "membership": frozenset({"member_of", "collaboration", "supported", "taught"}),
}
# Engineering credits connect nearly everyone through a few mix engineers,
# which makes paths technically true but uninformative; opt-in only.
DEFAULT_CATEGORIES = frozenset(CATEGORIES) - {"engineering"}

PERFORMER_ROLES = frozenset({"primary", "featured"})
CONTRIBUTOR_ROLES = frozenset({"vocal", "instrument", "performer", "programming", "arranger", "conductor", "remixer"})
REL_KIND = {
    "member_of": "member_of",
    "subgroup": "member_of",
    "is_person": "member_of",
    "collaboration": "collaboration",
    "supporting_musician": "supported",
    "teacher": "taught",
}


def kinds_for(categories: Iterable[str]) -> frozenset[str]:
    unknown = set(categories) - set(CATEGORIES)
    if unknown:
        raise ValueError(f"unknown relation categories: {sorted(unknown)}")
    return frozenset().union(*(CATEGORIES[c] for c in categories))


@dataclass(frozen=True)
class Evidence:
    """One fact-backed reason two artists are connected.

    ``subject`` is the track, album, or relationship the fact is about.
    Roles are given for the edge's (a, b) orientation, a < b by ID.
    """

    kind: str
    subject_type: str  # track | album | relationship
    subject_id: str
    a_role: str
    b_role: str


@dataclass
class Edge:
    a: str
    b: str
    evidence: list[Evidence] = field(default_factory=list)
    kind_weight: dict[str, float] = field(default_factory=dict)
    _seen: set[Evidence] = field(default_factory=set, repr=False)

    def strength(self, kinds: frozenset[str]) -> float:
        return sum(w for k, w in self.kind_weight.items() if k in kinds)

    def other(self, node: str) -> str:
        return self.b if node == self.a else self.a

    def role_of(self, node: str, ev: Evidence) -> str:
        return ev.a_role if node == self.a else ev.b_role


@dataclass(frozen=True)
class ArtistNode:
    id: str
    name: str
    hydrated: bool
    artist_type: str | None
    country: str | None
    disambiguation: str | None
    genres: tuple[str, ...]


class ArtistGraph:
    def __init__(self, version: str) -> None:
        self.version = version
        self.nodes: dict[str, ArtistNode] = {}
        self.edges: dict[tuple[str, str], Edge] = {}
        self.adj: dict[str, dict[str, Edge]] = defaultdict(dict)
        self.subject_titles: dict[str, str] = {}
        self._adjacency_cache: dict[frozenset[str], dict[str, dict[str, float]]] = {}

    # -- construction -------------------------------------------------------

    def add_evidence(
        self, u: str, v: str, kind: str, subject_type: str, subject_id: str, u_role: str, v_role: str
    ) -> None:
        if u == v or u not in self.nodes or v not in self.nodes:
            return
        a, b = (u, v) if u < v else (v, u)
        a_role, b_role = (u_role, v_role) if u < v else (v_role, u_role)
        edge = self.edges.get((a, b))
        if edge is None:
            edge = self.edges[(a, b)] = Edge(a, b)
            self.adj[a][b] = edge
            self.adj[b][a] = edge
        evidence = Evidence(kind, subject_type, subject_id, a_role, b_role)
        if evidence in edge._seen:
            return
        edge._seen.add(evidence)
        edge.evidence.append(evidence)
        edge.kind_weight[kind] = edge.kind_weight.get(kind, 0.0) + KIND_WEIGHTS[kind]

    # -- queries ------------------------------------------------------------

    def edge(self, u: str, v: str) -> Edge | None:
        return self.edges.get((u, v) if u < v else (v, u))

    def adjacency(self, kinds: frozenset[str]) -> Mapping[str, Mapping[str, float]]:
        """Weighted adjacency restricted to evidence kinds (memoized per kind set).

        Every artist appears as a key, including isolated ones, so algorithms
        see the full node set.
        """
        cached = self._adjacency_cache.get(kinds)
        if cached is not None:
            return cached
        adjacency: dict[str, dict[str, float]] = {node: {} for node in self.nodes}
        for (a, b), edge in self.edges.items():
            strength = edge.strength(kinds)
            if strength > 0:
                adjacency[a][b] = strength
                adjacency[b][a] = strength
        self._adjacency_cache[kinds] = adjacency
        return adjacency

    def stats(self) -> dict[str, int]:
        return {
            "artists": len(self.nodes),
            "hydrated_artists": sum(1 for n in self.nodes.values() if n.hydrated),
            "edges": len(self.edges),
            "evidence": sum(len(e.evidence) for e in self.edges.values()),
        }


# ---------------------------------------------------------------------------
# Building from the database
# ---------------------------------------------------------------------------


def _pairs_from_roles(graph: ArtistGraph, subject_type: str, subject_id: str, roles: Mapping[str, set[str]]) -> None:
    """Emit evidence for every pair of artists credited on one track/album."""
    performers = sorted(a for a, r in roles.items() if r & PERFORMER_ROLES)
    producers = sorted(a for a, r in roles.items() if "producer" in r)
    contributors = sorted(a for a, r in roles.items() if r & CONTRIBUTOR_ROLES)
    engineers = sorted(a for a, r in roles.items() if "engineer" in r)
    sampled = sorted(a for a, r in roles.items() if "sampled" in r)

    def performer_role(artist: str) -> str:
        return "primary" if "primary" in roles[artist] else "featured"

    def contributor_role(artist: str) -> str:
        return sorted(roles[artist] & CONTRIBUTOR_ROLES)[0]

    for u, v in itertools.combinations(performers, 2):
        graph.add_evidence(u, v, "performed_with", subject_type, subject_id, performer_role(u), performer_role(v))
    for u, v in itertools.combinations(producers, 2):
        graph.add_evidence(u, v, "co_produced", subject_type, subject_id, "producer", "producer")
    for p in performers:
        p_role = performer_role(p)
        for u in producers:
            graph.add_evidence(u, p, "produced_for", subject_type, subject_id, "producer", p_role)
        for u in contributors:
            graph.add_evidence(u, p, "contributed_to", subject_type, subject_id, contributor_role(u), p_role)
        for u in engineers:
            graph.add_evidence(u, p, "engineered", subject_type, subject_id, "engineer", p_role)
        for u in sampled:
            graph.add_evidence(u, p, "sampled", subject_type, subject_id, "sampled", p_role)


def build_graph(session: Session, version: str) -> ArtistGraph:
    started = time.perf_counter()
    graph = ArtistGraph(version)

    genres_by_artist: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for artist_id, name, votes in session.execute(
        select(m.ArtistGenre.artist_id, m.Genre.name, m.ArtistGenre.votes).join(m.Genre)
    ):
        genres_by_artist[artist_id].append((votes, name))

    for row in session.execute(
        select(
            m.Artist.id,
            m.Artist.name,
            m.Artist.hydrated,
            m.Artist.artist_type,
            m.Artist.country,
            m.Artist.disambiguation,
        )
    ):
        top_genres = tuple(
            name for _, name in sorted(genres_by_artist.get(row.id, []), key=lambda g: (-g[0], g[1]))[:5]
        )
        graph.nodes[row.id] = ArtistNode(
            row.id, row.name, row.hydrated, row.artist_type, row.country, row.disambiguation, top_genres
        )

    track_roles: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for track_id, artist_id, role in session.execute(
        select(m.TrackCredit.track_id, m.TrackCredit.artist_id, m.TrackCredit.role).order_by(
            m.TrackCredit.track_id, m.TrackCredit.artist_id
        )
    ):
        track_roles[track_id][artist_id].add(role)
    for track_id, roles in track_roles.items():
        _pairs_from_roles(graph, "track", track_id, roles)

    album_roles: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for album_id, artist_id in session.execute(select(m.AlbumArtist.album_id, m.AlbumArtist.artist_id)):
        album_roles[album_id][artist_id].add("primary")
    for album_id, artist_id, role in session.execute(
        select(m.AlbumCredit.album_id, m.AlbumCredit.artist_id, m.AlbumCredit.role)
    ):
        album_roles[album_id][artist_id].add(role)
    for album_id, roles in sorted(album_roles.items()):
        _pairs_from_roles(graph, "album", album_id, roles)

    role_label = {
        "member_of": ("member", "group"),
        "subgroup": ("subgroup", "group"),
        "is_person": ("persona", "person"),
        "collaboration": ("collaborator", "project"),
        "supporting_musician": ("supporting musician", "artist"),
        "teacher": ("teacher", "student"),
    }
    for rel in session.execute(select(m.ArtistRelationship).order_by(m.ArtistRelationship.id)).scalars():
        kind = REL_KIND.get(rel.rel_type)
        if kind is None:
            continue
        src_role, tgt_role = role_label[rel.rel_type]
        graph.add_evidence(rel.source_artist_id, rel.target_artist_id, kind, "relationship", rel.id, src_role, tgt_role)

    for track_id, title in session.execute(select(m.Track.id, m.Track.title)):
        graph.subject_titles[track_id] = title
    for album_id, title in session.execute(select(m.Album.id, m.Album.title)):
        graph.subject_titles[album_id] = title

    log.info(
        "graph projection built",
        extra={"version": version, **graph.stats(), "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)},
    )
    return graph
