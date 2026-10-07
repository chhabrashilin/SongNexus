"""Projection, filters, explanations, collaborations and comparison on a small catalog.

The catalog (artist IDs are their names):

    rec1: Kendrick (primary) feat. SZA, produced by Sounwave
    rec2: SZA (primary), produced by Sounwave, with Thundercat on bass
    rec3: Thundercat (primary) feat. Flying Lotus, engineered by Mixer
    rel1: release by Kendrick and SZA together (release-level credit)
    rel:  Thundercat is a member of Suicidal Tendencies
    labels: Kendrick and SZA on TDE within 3 years; Thundercat on Brainfeeder
"""

import itertools

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from songnexus.core.graph import algorithms as alg
from songnexus.core.graph.collaborations import CollaborationType, collaborations
from songnexus.core.graph.compare import compare
from songnexus.core.graph.explain import MessageId, explain_edge, explain_path
from songnexus.core.graph.filters import NodeFilter, genre_coverage
from songnexus.core.graph.model import (
    DEFAULT_CATEGORIES,
    ArtistGraph,
    Category,
    EdgeKind,
    SubjectType,
    kinds_for,
)
from songnexus.core.graph.projection import (
    ArtistFact,
    CatalogFacts,
    CreditFact,
    GenreFact,
    LabelReleaseFact,
    RelationFact,
    build_graph,
)
from songnexus.core.model import CreditRole, RelationType

R, REL = SubjectType.RECORDING, SubjectType.RELEASE
DEFAULT = kinds_for(DEFAULT_CATEGORIES)
ALL = kinds_for(Category)
ARTISTS = ["Kendrick", "SZA", "Sounwave", "Thundercat", "FlyingLotus", "Mixer", "Suicidal", "Loner"]


def facts() -> CatalogFacts:
    c = CreditRole
    return CatalogFacts(
        artists=[ArtistFact(a, a, "full" if a != "Mixer" else "stub") for a in ARTISTS],
        genres=[
            GenreFact("Kendrick", "g-hiphop", "hip hop", 8),
            GenreFact("Kendrick", "g-jazz", "jazz", 2),
            GenreFact("SZA", "g-rnb", "r and b", 9),
            GenreFact("SZA", "g-hiphop", "hip hop", 1),
            GenreFact("Thundercat", "g-jazz", "jazz", 5),
            GenreFact("Thundercat", "g-funk", "funk", 5),
            GenreFact("FlyingLotus", "g-electronic", "electronic", 3),
            GenreFact("Suicidal", "g-punk", "punk", 4),
        ],
        credits=[
            CreditFact(R, "rec1", "Kendrick", c.PRIMARY),
            CreditFact(R, "rec1", "SZA", c.FEATURED),
            CreditFact(R, "rec1", "Sounwave", c.PRODUCER),
            CreditFact(R, "rec2", "SZA", c.PRIMARY),
            CreditFact(R, "rec2", "Sounwave", c.PRODUCER),
            CreditFact(R, "rec2", "Thundercat", c.INSTRUMENT),
            CreditFact(R, "rec3", "Thundercat", c.PRIMARY),
            CreditFact(R, "rec3", "FlyingLotus", c.FEATURED),
            CreditFact(R, "rec3", "Mixer", c.ENGINEER),
            CreditFact(REL, "rel1", "Kendrick", c.PRIMARY),
            CreditFact(REL, "rel1", "SZA", c.PRIMARY),
        ],
        relations=[RelationFact("r1", "Thundercat", "Suicidal", RelationType.MEMBER_OF)],
        label_releases=[
            LabelReleaseFact("tde", "relA", "Kendrick", 2012),
            LabelReleaseFact("tde", "relB", "SZA", 2014),
            LabelReleaseFact("bf", "relC", "Thundercat", 2017),
        ],
        titles={"rec1": "Song One", "rec2": "Song Two", "rec3": "Song Three", "rel1": "Joint"},
        years={"rec1": 2017, "rec2": 2017, "rec3": 2015, "rel1": 2018},
    )


@pytest.fixture(scope="module")
def graph() -> ArtistGraph:
    return build_graph(facts(), "test")


def kinds_between(graph: ArtistGraph, u: str, v: str) -> set[EdgeKind]:
    edge = graph.edge(u, v)
    return set() if edge is None else {e.kind for e in edge.evidence}


def test_projection_derives_edge_kinds(graph: ArtistGraph) -> None:
    assert kinds_between(graph, "Kendrick", "SZA") == {
        EdgeKind.PERFORMED_WITH,
        EdgeKind.LABEL_MATES,
    }
    assert kinds_between(graph, "Sounwave", "Kendrick") == {EdgeKind.PRODUCED_FOR}
    assert kinds_between(graph, "Thundercat", "SZA") == {EdgeKind.CONTRIBUTED_TO}
    assert kinds_between(graph, "Mixer", "Thundercat") == {EdgeKind.ENGINEERED}
    assert kinds_between(graph, "Thundercat", "Suicidal") == {EdgeKind.MEMBER_OF}
    assert graph.neighbors["Loner"] == {}


def test_strength_sums_evidence_weights(graph: ArtistGraph) -> None:
    edge = graph.edge("Kendrick", "SZA")
    assert edge is not None
    # rec1 (featured) + rel1 (both primary) = 2 x performed_with; label mates off.
    assert edge.strength(DEFAULT) == pytest.approx(2.0)
    assert edge.strength(ALL) == pytest.approx(2.2)


def test_default_categories_hide_engineering_and_labels(graph: ArtistGraph) -> None:
    assert "Mixer" not in graph.adjacency(DEFAULT)["Thundercat"]
    assert "Mixer" in graph.adjacency(ALL)["Thundercat"]


def test_projection_is_deterministic() -> None:
    a, b = build_graph(facts(), "v"), build_graph(facts(), "v")
    assert a.edges.keys() == b.edges.keys()
    assert all(a.edges[k].evidence == b.edges[k].evidence for k in a.edges)


def test_relation_roles_follow_direction(graph: ArtistGraph) -> None:
    edge = graph.edge("Thundercat", "Suicidal")
    assert edge is not None
    (evidence,) = edge.evidence
    assert edge.role_of("Thundercat", evidence) == "member"
    assert edge.role_of("Suicidal", evidence) == "group"


def test_genre_shares(graph: ArtistGraph) -> None:
    assert graph.nodes["Kendrick"].genre_share("g-hiphop") == pytest.approx(0.8)
    assert graph.nodes["SZA"].genre_share("g-hiphop") == pytest.approx(0.1)


def test_genre_filter_uses_share_threshold(graph: ArtistGraph) -> None:
    hip_hop = NodeFilter(genre_ids=frozenset({"g-hiphop"}))
    assert hip_hop.allows(graph.nodes["Kendrick"])
    assert not hip_hop.allows(graph.nodes["SZA"])  # 10% < 20%
    assert hip_hop.allows(graph.nodes["Sounwave"])  # unknown genre: kept by default
    strict = NodeFilter(genre_ids=frozenset({"g-hiphop"}), include_unknown_genre=False)
    assert not strict.allows(graph.nodes["Sounwave"])


def test_genre_coverage(graph: ArtistGraph) -> None:
    assert genre_coverage(graph, ["Kendrick", "Sounwave"]) == 0.5
    assert genre_coverage(graph, []) == 0.0


@settings(max_examples=200, deadline=None)
@given(
    st.sampled_from(ARTISTS),
    st.sampled_from(ARTISTS),
    st.frozensets(st.sampled_from(ARTISTS)),
    st.frozensets(st.sampled_from(["g-hiphop", "g-jazz", "g-rnb", "g-funk", "g-punk"])),
)
def test_filtered_artists_never_appear_on_paths(
    source: str, target: str, blocked: frozenset[str], genres: frozenset[str]
) -> None:
    """AC-3.3 and AC-17.1: no step passes through an excluded artist."""
    graph = build_graph(facts(), "prop")
    node_filter = NodeFilter(genre_ids=genres, blocked=blocked)
    allowed = node_filter.predicate(graph)
    adjacency = graph.adjacency(ALL)
    for search in (alg.bidirectional_bfs_path, alg.dijkstra_path):
        result = search(adjacency, source, target, allowed=allowed)
        if result.path is not None and allowed is not None:
            assert all(allowed(n) for n in result.path[1:-1])
    for collaborator_type in CollaborationType:
        for item in collaborations(graph, source, collaborator_type, node_filter):
            assert node_filter.allows(graph.nodes[item.artist_id])


def test_explanations_are_oriented_and_ordered(graph: ArtistGraph) -> None:
    edge = graph.edge("Kendrick", "SZA")
    assert edge is not None
    from_sza = explain_edge(graph, edge, "SZA", DEFAULT)
    assert [(e.message_id, e.subject_title) for e in from_sza] == [
        (MessageId.PERFORMED_TOGETHER, "Joint"),
        (MessageId.FEATURED, "Song One"),
    ]
    featured = from_sza[1]
    assert (featured.from_role, featured.to_role) == ("featured", "primary")


def test_explain_path_covers_every_step(graph: ArtistGraph) -> None:
    path = alg.bidirectional_bfs_path(graph.adjacency(DEFAULT), "Kendrick", "FlyingLotus").path
    assert path is not None
    steps = explain_path(graph, path, DEFAULT)
    assert len(steps) == len(path) - 1
    assert all(steps)
    with pytest.raises(ValueError, match="no evidence"):
        explain_path(graph, ("Kendrick", "Loner"), DEFAULT)


def test_collaborations_by_type(graph: ArtistGraph) -> None:
    features = collaborations(graph, "SZA", CollaborationType.FEATURE)
    assert [(c.artist_id, c.count, c.first_year, c.last_year) for c in features] == [
        ("Kendrick", 2, 2017, 2018)
    ]
    production = collaborations(graph, "SZA", CollaborationType.PRODUCTION)
    assert [(c.artist_id, c.count) for c in production] == [("Sounwave", 2)]
    credits = collaborations(graph, "SZA", CollaborationType.CREDIT)
    assert [c.artist_id for c in credits] == ["Thundercat"]
    assert [c.artist_id for c in collaborations(graph, "Thundercat", CollaborationType.BAND)] == [
        "Suicidal"
    ]


def test_compare_mutual_collaborators_is_exact_intersection(graph: ArtistGraph) -> None:
    """AC-5.1, checked for every pair."""
    adjacency = graph.adjacency(DEFAULT)
    for a, b in itertools.combinations(ARTISTS, 2):
        result = compare(graph, a, b, DEFAULT)
        assert set(result.mutual_collaborators) == set(adjacency[a]) & set(adjacency[b])
        assert result.directly_connected == (b in adjacency[a])


def test_compare_genres_and_path(graph: ArtistGraph) -> None:
    result = compare(graph, "Kendrick", "SZA", DEFAULT)
    assert [g.genre_id for g in result.shared_genres] == ["g-hiphop"]
    assert result.genre_overlap == pytest.approx(0.1)
    assert result.mutual_collaborators == ("Sounwave",)
    assert result.path.path == ("Kendrick", "SZA")
    assert result.counts_a[CollaborationType.FEATURE] == 1
    assert compare(graph, "Kendrick", "Sounwave", DEFAULT).genre_overlap is None


def test_adjacency_cache_is_bounded() -> None:
    """QA Q8: request-chosen category sets can't grow memory without bound."""
    from itertools import combinations

    from songnexus.core.graph.model import MAX_CACHED_ADJACENCIES

    graph = build_graph(facts(), "lru")
    for size in range(1, 4):
        for combo in combinations(list(Category), size):
            graph.adjacency(kinds_for(combo))
    assert len(graph._adjacency_cache) == MAX_CACHED_ADJACENCIES
    assert graph.genre_ids == {"g-hiphop", "g-jazz", "g-rnb", "g-funk", "g-electronic", "g-punk"}
