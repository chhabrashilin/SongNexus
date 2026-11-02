"""Projects catalog facts into the in-memory artist graph.

``build_graph`` is pure: it takes plain fact records (produced by the storage
reader, or built directly in tests) and returns an ``ArtistGraph``. The graph is
a read model, rebuilt from facts after ingestion and never written back.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from songnexus.core.graph.model import ArtistGraph, ArtistNode, EdgeKind, GenreShare, SubjectType
from songnexus.core.model import CONTRIBUTOR_ROLES, PERFORMER_ROLES, CreditRole, RelationType

# Labels with more artists than this are too broad for "label mates" to mean
# anything (a major label connects thousands of unrelated artists).
MAX_LABEL_ARTISTS = 40
# Releases on the same label within this many years make two artists label mates.
LABEL_MATE_YEARS = 3
# Genres kept per artist for filtering and counts. Two sources give artists more
# genres than one; keeping only a top 5 would hide real ones from filters.
MAX_NODE_GENRES = 10


@dataclass(frozen=True)
class ArtistFact:
    """An artist row."""

    id: str
    name: str
    detail_level: str
    artist_type: str | None = None
    country: str | None = None
    disambiguation: str | None = None
    begin_date: str | None = None


@dataclass(frozen=True)
class GenreFact:
    """An artist-genre association with its vote count, from one source."""

    artist_id: str
    genre_id: str
    genre_name: str
    votes: int
    source_id: str = "musicbrainz-supplementary"


@dataclass(frozen=True)
class GenreInfo:
    """A vocabulary genre and its direct parents."""

    id: str
    name: str
    parent_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CreditFact:
    """An artist's role on a recording or release (release artists are ``primary``)."""

    subject_type: SubjectType
    subject_id: str
    artist_id: str
    role: CreditRole


@dataclass(frozen=True)
class RelationFact:
    """A directed artist relation, ``subject <type> object``."""

    id: str
    subject_artist_id: str
    object_artist_id: str
    relation_type: RelationType


@dataclass(frozen=True)
class LabelReleaseFact:
    """A release on a label, with one of the release's primary artists."""

    label_id: str
    release_id: str
    artist_id: str
    year: int | None


@dataclass
class CatalogFacts:
    """Everything the projection reads."""

    artists: Iterable[ArtistFact]
    genres: Iterable[GenreFact] = ()
    vocabulary: Iterable[GenreInfo] = ()
    credits: Iterable[CreditFact] = ()
    relations: Iterable[RelationFact] = ()
    label_releases: Iterable[LabelReleaseFact] = ()
    titles: Mapping[str, str] = field(default_factory=dict)
    years: Mapping[str, int] = field(default_factory=dict)


# Relation type -> (edge kind, subject's role, object's role).
_RELATION_EDGES: Mapping[RelationType, tuple[EdgeKind, str, str]] = {
    RelationType.MEMBER_OF: (EdgeKind.MEMBER_OF, "member", "group"),
    RelationType.HAS_SUBGROUP: (EdgeKind.MEMBER_OF, "group", "subgroup"),
    RelationType.PERFORMS_AS: (EdgeKind.MEMBER_OF, "person", "performance name"),
    RelationType.COLLABORATION_IN: (EdgeKind.COLLABORATION, "collaborator", "project"),
    RelationType.SUPPORTED: (EdgeKind.SUPPORTED, "supporting musician", "artist"),
    RelationType.TAUGHT: (EdgeKind.TAUGHT, "teacher", "student"),
}


def _genre_shares(facts: Iterable[GenreFact]) -> dict[str, tuple[GenreShare, ...]]:
    """Per artist: each source's vote shares, averaged over the sources with data.

    Sources count in different units (tag votes, tagged masters), so votes are
    never added across sources; each source contributes a distribution that sums
    to 1, and a genre one source lacks counts as 0 from that source.
    """
    votes: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
    names: dict[str, str] = {}
    for fact in facts:
        if fact.votes > 0:
            votes[fact.artist_id][fact.source_id][fact.genre_id] = fact.votes
            names[fact.genre_id] = fact.genre_name
    shares: dict[str, tuple[GenreShare, ...]] = {}
    for artist_id, by_source in votes.items():
        combined: dict[str, float] = defaultdict(float)
        asserted_by: dict[str, set[str]] = defaultdict(set)
        for source_id, genre_votes in by_source.items():
            total = sum(genre_votes.values())
            for genre_id, count in genre_votes.items():
                combined[genre_id] += count / total / len(by_source)
                asserted_by[genre_id].add(source_id)
        ranked = sorted(combined.items(), key=lambda kv: (-kv[1], names[kv[0]]))
        shares[artist_id] = tuple(
            GenreShare(g, names[g], share, tuple(sorted(asserted_by[g])))
            for g, share in ranked[:MAX_NODE_GENRES]
        )
    return shares


def _add_credit_pairs(
    graph: ArtistGraph,
    subject_type: SubjectType,
    subject_id: str,
    roles: Mapping[str, set[CreditRole]],
) -> None:
    """Adds evidence for every meaningful pair of artists credited on one subject."""
    performers = sorted(a for a, r in roles.items() if r & PERFORMER_ROLES)
    producers = sorted(a for a, r in roles.items() if CreditRole.PRODUCER in r)
    contributors = sorted(a for a, r in roles.items() if r & CONTRIBUTOR_ROLES)
    engineers = sorted(a for a, r in roles.items() if CreditRole.ENGINEER in r)
    sampled = sorted(a for a, r in roles.items() if CreditRole.SAMPLED in r)

    def performer_role(artist: str) -> str:
        return "primary" if CreditRole.PRIMARY in roles[artist] else "featured"

    def contributor_role(artist: str) -> str:
        return min(roles[artist] & CONTRIBUTOR_ROLES).value

    def add(u: str, v: str, kind: EdgeKind, u_role: str, v_role: str) -> None:
        graph.add_evidence(u, v, kind, subject_type, subject_id, u_role=u_role, v_role=v_role)

    for u, v in itertools.combinations(performers, 2):
        add(u, v, EdgeKind.PERFORMED_WITH, performer_role(u), performer_role(v))
    for u, v in itertools.combinations(producers, 2):
        add(u, v, EdgeKind.CO_PRODUCED, "producer", "producer")
    for performer in performers:
        role = performer_role(performer)
        for u in producers:
            add(u, performer, EdgeKind.PRODUCED_FOR, "producer", role)
        for u in contributors:
            add(u, performer, EdgeKind.CONTRIBUTED_TO, contributor_role(u), role)
        for u in engineers:
            add(u, performer, EdgeKind.ENGINEERED, "engineer", role)
        for u in sampled:
            add(u, performer, EdgeKind.SAMPLED, "sampled", role)


def _add_label_mates(graph: ArtistGraph, facts: Iterable[LabelReleaseFact]) -> None:
    years: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for fact in facts:
        if fact.year is not None:
            years[fact.label_id][fact.artist_id].add(fact.year)
    for label_id in sorted(years):
        artists = years[label_id]
        if len(artists) > MAX_LABEL_ARTISTS:
            continue
        for u, v in itertools.combinations(sorted(artists), 2):
            if any(abs(x - y) <= LABEL_MATE_YEARS for x in artists[u] for y in artists[v]):
                graph.add_evidence(
                    u,
                    v,
                    EdgeKind.LABEL_MATES,
                    SubjectType.LABEL,
                    label_id,
                    u_role="label mate",
                    v_role="label mate",
                )


def build_graph(facts: CatalogFacts, version: str) -> ArtistGraph:
    """Builds the artist graph from catalog facts. Deterministic for equal inputs."""
    graph = ArtistGraph(version)
    shares = _genre_shares(facts.genres)
    for artist in sorted(facts.artists, key=lambda a: a.id):
        graph.add_node(
            ArtistNode(
                id=artist.id,
                name=artist.name,
                detail_level=artist.detail_level,
                artist_type=artist.artist_type,
                country=artist.country,
                disambiguation=artist.disambiguation,
                begin_date=artist.begin_date,
                genres=shares.get(artist.id, ()),
            )
        )

    roles: dict[tuple[SubjectType, str], dict[str, set[CreditRole]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for credit in facts.credits:
        roles[(credit.subject_type, credit.subject_id)][credit.artist_id].add(credit.role)
    for (subject_type, subject_id), subject_roles in sorted(roles.items()):
        _add_credit_pairs(graph, subject_type, subject_id, subject_roles)

    for relation in sorted(facts.relations, key=lambda r: r.id):
        kind, subject_role, object_role = _RELATION_EDGES[relation.relation_type]
        graph.add_evidence(
            relation.subject_artist_id,
            relation.object_artist_id,
            kind,
            SubjectType.RELATION,
            relation.id,
            u_role=subject_role,
            v_role=object_role,
        )

    _add_label_mates(graph, facts.label_releases)
    for genre in facts.vocabulary:
        graph.genre_names[genre.id] = genre.name
        if genre.parent_ids:
            graph.genre_parents[genre.id] = frozenset(genre.parent_ids)
    for node in graph.nodes.values():
        for share in node.genres:
            graph.genre_names.setdefault(share.genre_id, share.name)
    graph.subject_titles.update(facts.titles)
    graph.subject_years.update(facts.years)
    return graph
