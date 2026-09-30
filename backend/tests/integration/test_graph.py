"""Projection, graph service, and explanations over the synthetic dataset."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from songnexus.core.config import Settings
from songnexus.core.errors import InvalidRequestError, NotFoundError
from songnexus.core.ids import artist_id_for_mbid
from songnexus.graph.projection import DEFAULT_CATEGORIES, KIND_WEIGHTS, kinds_for
from songnexus.readmodel import ReadModelStore
from songnexus.services.graph_service import GraphService, parse_categories
from tests.fixtures import mbid


def aid(key: str) -> str:
    return artist_id_for_mbid(mbid(key))


@pytest.fixture
def service(loaded_engine: Engine, settings: Settings) -> GraphService:
    return GraphService(ReadModelStore(loaded_engine), settings)


def test_projection_builds_expected_evidence(service: GraphService) -> None:
    graph = service.model.graph
    edge = graph.edge(aid("alpha"), aid("beta"))
    assert edge is not None
    kinds = {ev.kind for ev in edge.evidence}
    assert kinds == {"performed_with"}
    # The merged remaster must not double-count the same track.
    assert edge.strength(kinds_for(DEFAULT_CATEGORIES)) == KIND_WEIGHTS["performed_with"]
    producer_edge = graph.edge(aid("delta"), aid("gamma"))
    assert producer_edge is not None and {ev.kind for ev in producer_edge.evidence} == {"produced_for"}


def test_engineering_is_excluded_by_default_but_available(service: GraphService) -> None:
    default = service.model.graph.adjacency(kinds_for(DEFAULT_CATEGORIES))
    assert aid("eta") not in default[aid("alpha")]
    with_engineering = service.model.graph.adjacency(kinds_for({"engineering"}))
    assert aid("eta") in with_engineering[aid("alpha")]


def test_shortest_path_crosses_production_and_contribution(service: GraphService) -> None:
    result = service.path(aid("beta"), aid("epsilon"), "shortest", DEFAULT_CATEGORIES, max_depth=6, alternatives=1)
    assert result.found and result.path is not None
    names = [n.name for n in result.path.nodes]
    assert names == ["Beta Singer", "Delta Producer", "Gamma Pianist", "Epsilon Drummer"]
    assert all(hop.evidence for hop in result.path.hops)
    # Beta is only featured on "Skyline", so the sentence must not call it Beta's song.
    assert "Delta Producer produced “Skyline” (featuring Beta Singer)" in result.explanation
    assert "Epsilon Drummer is credited (instrument) on Gamma Pianist's “Nocturne”" in result.explanation
    # The alternative route goes through the band instead of the drum credit.
    assert [n.name for n in result.alternatives[0].nodes][-2:] == ["Zeta Quartet", "Epsilon Drummer"]


def test_primary_artists_get_the_possessive(service: GraphService) -> None:
    evidence = service.edge_evidence(aid("delta"), aid("alpha"), DEFAULT_CATEGORIES).evidence
    assert evidence[0].sentence == "Delta Producer produced Alpha Rapper's “Skyline”"


def test_membership_only_path(service: GraphService) -> None:
    result = service.path(aid("gamma"), aid("epsilon"), "shortest", frozenset({"membership"}), 6, 0)
    assert result.path is not None
    assert [n.name for n in result.path.nodes] == ["Gamma Pianist", "Zeta Quartet", "Epsilon Drummer"]


def test_path_respects_depth_and_categories(service: GraphService) -> None:
    shallow = service.path(aid("beta"), aid("epsilon"), "shortest", DEFAULT_CATEGORIES, max_depth=2, alternatives=0)
    assert not shallow.found
    assert "not that no real-world connection exists" in shallow.explanation
    no_membership = service.path(
        aid("beta"), aid("epsilon"), "shortest", frozenset({"performance", "production"}), 6, 0
    )
    assert not no_membership.found


def test_isolated_artist_has_no_path(service: GraphService) -> None:
    assert not service.path(aid("alpha"), aid("theta"), "shortest", DEFAULT_CATEGORIES, 6, 0).found


def test_strongest_mode_and_alternatives(service: GraphService) -> None:
    result = service.path(aid("alpha"), aid("gamma"), "strongest", DEFAULT_CATEGORIES, 6, 2)
    assert result.found and result.algorithm.startswith("dijkstra")
    assert result.path is not None and result.path.cost is not None


def test_path_results_are_cached_per_read_model(service: GraphService) -> None:
    args = (aid("beta"), aid("epsilon"), "shortest", DEFAULT_CATEGORIES, 6, 0)
    first = service.path(*args)
    second = service.path(*args)
    assert first.path == second.path
    service._store.reload()  # new read model -> fresh cache
    assert service.path(*args).path == first.path


def test_neighborhood_limits_and_truncation(service: GraphService) -> None:
    payload = service.neighborhood(aid("delta"), DEFAULT_CATEGORIES, limit=1, depth=1, min_strength=0)
    assert payload.truncated and payload.total_neighbors == 3
    assert len([n for n in payload.nodes if n.depth == 1]) == 1
    two_hop = service.neighborhood(aid("beta"), DEFAULT_CATEGORIES, limit=10, depth=2, min_strength=0)
    assert any(n.depth == 2 for n in two_hop.nodes)


def test_edge_evidence_and_errors(service: GraphService) -> None:
    evidence = service.edge_evidence(aid("gamma"), aid("zeta"), DEFAULT_CATEGORIES)
    assert evidence.evidence[0].sentence == "Gamma Pianist is a member of Zeta Quartet"
    with pytest.raises(NotFoundError):
        service.edge_evidence(aid("alpha"), aid("theta"), DEFAULT_CATEGORIES)
    with pytest.raises(NotFoundError):
        service.path(aid("alpha"), "00000000-0000-0000-0000-000000000000", "shortest", DEFAULT_CATEGORIES, 6, 0)
    with pytest.raises(InvalidRequestError):
        parse_categories(["performance", "gossip"])


def test_centrality_ranks_the_producer_hub_first(service: GraphService) -> None:
    result = service.centrality("betweenness", DEFAULT_CATEGORIES, limit=3, scope="all")
    assert result.exact
    assert result.results[0].name == "Delta Producer"
    pagerank = service.centrality("pagerank", DEFAULT_CATEGORIES, limit=10, scope="hydrated")
    assert {r.name for r in pagerank.results} <= {"Alpha Rapper", "Gamma Pianist", "Zeta Quartet"}
