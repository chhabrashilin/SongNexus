"""The artist graph: nodes are artists, edges carry every fact that connects two.

Edge kinds and their weights (strength is the sum of an edge's evidence weights
for the enabled kinds):

    kind             derived from                                       weight
    ---------------  -------------------------------------------------  ------
    performed_with   both credited performers on a recording/release      1.0
    produced_for     one produced a recording/release the other performed 1.0
    co_produced      both produced the same recording                     0.6
    contributed_to   vocal, instrument, arrangement... on the other's      0.6
    sampled          the other's recording samples this artist            0.4
    member_of        membership, subgroup, persona                        3.0
    collaboration    part of a collaboration project                      2.0
    supported        supporting musician                                  1.0
    taught           teacher                                              1.0
    label_mates      releases on the same label within a few years        0.2
    engineered       mix, recording or mastering on the other's           0.25

The weights are a documented heuristic, exposed so they can be evaluated and
tuned (plan §16.1), not a claim of optimality.
"""

from __future__ import annotations

import enum
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


class EdgeKind(enum.StrEnum):
    """Why two artists are connected."""

    PERFORMED_WITH = "performed_with"
    PRODUCED_FOR = "produced_for"
    CO_PRODUCED = "co_produced"
    CONTRIBUTED_TO = "contributed_to"
    SAMPLED = "sampled"
    MEMBER_OF = "member_of"
    COLLABORATION = "collaboration"
    SUPPORTED = "supported"
    TAUGHT = "taught"
    LABEL_MATES = "label_mates"
    ENGINEERED = "engineered"


KIND_WEIGHTS: Mapping[EdgeKind, float] = MappingProxyType(
    {
        EdgeKind.PERFORMED_WITH: 1.0,
        EdgeKind.PRODUCED_FOR: 1.0,
        EdgeKind.CO_PRODUCED: 0.6,
        EdgeKind.CONTRIBUTED_TO: 0.6,
        EdgeKind.SAMPLED: 0.4,
        EdgeKind.MEMBER_OF: 3.0,
        EdgeKind.COLLABORATION: 2.0,
        EdgeKind.SUPPORTED: 1.0,
        EdgeKind.TAUGHT: 1.0,
        EdgeKind.LABEL_MATES: 0.2,
        EdgeKind.ENGINEERED: 0.25,
    }
)


class Category(enum.StrEnum):
    """A user-facing group of edge kinds that can be toggled."""

    FEATURES = "features"
    PRODUCERS = "producers"
    CONTRIBUTIONS = "contributions"
    SAMPLES = "samples"
    BANDS = "bands"
    LABELS = "labels"
    ENGINEERING = "engineering"


CATEGORY_KINDS: Mapping[Category, frozenset[EdgeKind]] = MappingProxyType(
    {
        Category.FEATURES: frozenset({EdgeKind.PERFORMED_WITH}),
        Category.PRODUCERS: frozenset({EdgeKind.PRODUCED_FOR, EdgeKind.CO_PRODUCED}),
        Category.CONTRIBUTIONS: frozenset({EdgeKind.CONTRIBUTED_TO}),
        Category.SAMPLES: frozenset({EdgeKind.SAMPLED}),
        Category.BANDS: frozenset(
            {EdgeKind.MEMBER_OF, EdgeKind.COLLABORATION, EdgeKind.SUPPORTED, EdgeKind.TAUGHT}
        ),
        Category.LABELS: frozenset({EdgeKind.LABEL_MATES}),
        Category.ENGINEERING: frozenset({EdgeKind.ENGINEERED}),
    }
)

# Label mates and engineers connect nearly everyone through a few big labels and
# mix engineers: technically true, rarely informative. Both are opt-in.
DEFAULT_CATEGORIES = frozenset(Category) - {Category.LABELS, Category.ENGINEERING}


def kinds_for(categories: Iterable[Category]) -> frozenset[EdgeKind]:
    """Returns the edge kinds enabled by a set of categories."""
    return frozenset().union(*(CATEGORY_KINDS[c] for c in categories))


class SubjectType(enum.StrEnum):
    """What a piece of evidence is about."""

    RECORDING = "recording"
    RELEASE = "release"
    RELATION = "relation"
    LABEL = "label"


@dataclass(frozen=True)
class Evidence:
    """One fact-backed reason two artists are connected.

    Roles are given in the edge's (a, b) orientation, where a < b by ID.

    Attributes:
        kind: The edge kind this evidence supports.
        subject_type: Whether it is about a recording, release, relation or label.
        subject_id: The canonical ID of that subject.
        a_role: Artist a's role (e.g. "primary", "producer", "member").
        b_role: Artist b's role.
    """

    kind: EdgeKind
    subject_type: SubjectType
    subject_id: str
    a_role: str
    b_role: str


@dataclass
class Edge:
    """All evidence connecting artists ``a`` and ``b`` (a < b)."""

    a: str
    b: str
    evidence: list[Evidence] = field(default_factory=list)
    kind_weight: dict[EdgeKind, float] = field(default_factory=dict)
    _seen: set[Evidence] = field(default_factory=set, repr=False)

    def strength(self, kinds: frozenset[EdgeKind]) -> float:
        """Returns the summed weight of this edge's evidence of the given kinds."""
        return sum(w for k, w in self.kind_weight.items() if k in kinds)

    def other(self, node: str) -> str:
        """Returns the endpoint that is not ``node``."""
        return self.b if node == self.a else self.a

    def role_of(self, node: str, evidence: Evidence) -> str:
        """Returns ``node``'s role in one piece of this edge's evidence."""
        return evidence.a_role if node == self.a else evidence.b_role


@dataclass(frozen=True)
class GenreShare:
    """A genre and its share of an artist's genre votes."""

    genre_id: str
    name: str
    share: float


@dataclass(frozen=True)
class ArtistNode:
    """An artist as the graph knows it."""

    id: str
    name: str
    detail_level: str
    artist_type: str | None = None
    country: str | None = None
    disambiguation: str | None = None
    begin_date: str | None = None
    genres: tuple[GenreShare, ...] = ()

    def genre_share(self, genre_id: str) -> float:
        """Returns this artist's vote share for a genre (0 when absent)."""
        return next((g.share for g in self.genres if g.genre_id == genre_id), 0.0)


MAX_CACHED_ADJACENCIES = 16


class ArtistGraph:
    """An immutable-after-build artist graph with cached adjacency views.

    Built once per catalog version and shared read-only across requests.
    """

    def __init__(self, version: str) -> None:
        self.version = version
        self.nodes: dict[str, ArtistNode] = {}
        self.edges: dict[tuple[str, str], Edge] = {}
        self.neighbors: dict[str, dict[str, Edge]] = {}
        self.subject_titles: dict[str, str] = {}
        self.subject_years: dict[str, int] = {}
        # Bounded: each entry is a full adjacency copy, and requests choose the key
        # (one per category combination), so an unbounded cache is a memory DoS.
        self._adjacency_cache: OrderedDict[frozenset[EdgeKind], dict[str, dict[str, float]]] = (
            OrderedDict()
        )
        self._genre_ids: frozenset[str] | None = None

    def add_node(self, node: ArtistNode) -> None:
        """Adds or replaces an artist."""
        self.nodes[node.id] = node
        self.neighbors.setdefault(node.id, {})
        self._genre_ids = None

    def add_evidence(
        self,
        u: str,
        v: str,
        kind: EdgeKind,
        subject_type: SubjectType,
        subject_id: str,
        *,
        u_role: str,
        v_role: str,
    ) -> None:
        """Records that ``u`` and ``v`` are connected by one fact (idempotent).

        Self-loops and unknown artists are ignored.
        """
        if u == v or u not in self.nodes or v not in self.nodes:
            return
        a, b = (u, v) if u < v else (v, u)
        a_role, b_role = (u_role, v_role) if u < v else (v_role, u_role)
        edge = self.edges.get((a, b))
        if edge is None:
            edge = self.edges[(a, b)] = Edge(a, b)
            self.neighbors[a][b] = edge
            self.neighbors[b][a] = edge
        evidence = Evidence(kind, subject_type, subject_id, a_role, b_role)
        if evidence in edge._seen:
            return
        edge._seen.add(evidence)
        edge.evidence.append(evidence)
        edge.kind_weight[kind] = edge.kind_weight.get(kind, 0.0) + KIND_WEIGHTS[kind]
        self._adjacency_cache.clear()

    def edge(self, u: str, v: str) -> Edge | None:
        """Returns the edge between two artists, if any."""
        return self.edges.get((u, v) if u < v else (v, u))

    def adjacency(self, kinds: frozenset[EdgeKind]) -> Mapping[str, Mapping[str, float]]:
        """Returns the weighted adjacency restricted to ``kinds`` (memoized).

        Every artist is a key, including isolated ones, so algorithms see the
        full node set.
        """
        cached = self._adjacency_cache.get(kinds)
        if cached is not None:
            self._adjacency_cache.move_to_end(kinds)
            return cached
        adjacency: dict[str, dict[str, float]] = {node: {} for node in self.nodes}
        for (a, b), edge in self.edges.items():
            strength = edge.strength(kinds)
            if strength > 0:
                adjacency[a][b] = strength
                adjacency[b][a] = strength
        self._adjacency_cache[kinds] = adjacency
        while len(self._adjacency_cache) > MAX_CACHED_ADJACENCIES:
            self._adjacency_cache.popitem(last=False)
        return adjacency

    @property
    def genre_ids(self) -> frozenset[str]:
        """Every genre any artist carries (computed once)."""
        if self._genre_ids is None:
            self._genre_ids = frozenset(g.genre_id for n in self.nodes.values() for g in n.genres)
        return self._genre_ids

    def stats(self) -> dict[str, int]:
        """Returns node, edge and evidence counts."""
        return {
            "artists": len(self.nodes),
            "detailedArtists": sum(1 for n in self.nodes.values() if n.detail_level != "stub"),
            "edges": len(self.edges),
            "evidence": sum(len(e.evidence) for e in self.edges.values()),
        }
