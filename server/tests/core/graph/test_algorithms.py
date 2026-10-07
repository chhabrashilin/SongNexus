"""Property tests of the graph algorithms against networkx as an oracle."""

import itertools
from collections.abc import Callable

import networkx as nx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from songnexus.core.graph import algorithms as alg

Adj = dict[str, dict[str, float]]


@st.composite
def graphs(draw: st.DrawFn, max_nodes: int = 14) -> Adj:
    n = draw(st.integers(min_value=2, max_value=max_nodes))
    nodes = [f"n{i:02d}" for i in range(n)]
    adj: Adj = {v: {} for v in nodes}
    pairs = [(a, b) for i, a in enumerate(nodes) for b in nodes[i + 1 :]]
    for a, b in draw(st.lists(st.sampled_from(pairs), unique=True, max_size=3 * n)):
        weight = draw(st.sampled_from([0.25, 0.5, 1.0, 2.0, 3.0]))
        adj[a][b] = adj[b][a] = weight
    return adj


def to_nx(adj: Adj, keep: Callable[[str], bool] = lambda _n: True) -> nx.Graph:
    graph = nx.Graph()
    graph.add_nodes_from(n for n in adj if keep(n))
    for a, neighbors in adj.items():
        for b, weight in neighbors.items():
            if keep(a) and keep(b):
                graph.add_edge(a, b, weight=weight, cost=1.0 / weight)
    return graph


def endpoints(adj: Adj) -> tuple[str, str]:
    nodes = sorted(adj)
    return nodes[0], nodes[-1]


def is_valid_path(adj: Adj, path: tuple[str, ...]) -> bool:
    return len(set(path)) == len(path) and all(b in adj[a] for a, b in itertools.pairwise(path))


def nx_hops(graph: nx.Graph, s: str, t: str) -> int | None:
    try:
        return int(nx.shortest_path_length(graph, s, t))
    except nx.NetworkXNoPath:
        return None


@settings(max_examples=150, deadline=None)
@given(graphs())
def test_bfs_and_bidirectional_bfs_find_shortest_paths(adj: Adj) -> None:
    s, t = endpoints(adj)
    expected = nx_hops(to_nx(adj), s, t)
    for search in (alg.bfs_path, alg.bidirectional_bfs_path):
        result = search(adj, s, t)
        if expected is None:
            assert result.path is None
        else:
            assert result.path is not None
            assert is_valid_path(adj, result.path)
            assert (result.path[0], result.path[-1]) == (s, t)
            assert len(result.path) - 1 == expected == result.cost


@settings(max_examples=150, deadline=None)
@given(graphs(), st.integers(min_value=0, max_value=2**14 - 1))
def test_predicates_exclude_nodes_inside_the_search(adj: Adj, mask: int) -> None:
    s, t = endpoints(adj)
    excluded = {n for i, n in enumerate(sorted(adj)) if mask >> i & 1} - {s, t}

    def allowed(node: str) -> bool:
        return node not in excluded

    expected = nx_hops(to_nx(adj, allowed), s, t)
    for search in (alg.bfs_path, alg.bidirectional_bfs_path, alg.dijkstra_path):
        result = search(adj, s, t, allowed=allowed)
        if expected is None:
            assert result.path is None
        else:
            assert result.path is not None
            assert not excluded & set(result.path)
            if search is not alg.dijkstra_path:
                assert len(result.path) - 1 == expected


@settings(max_examples=150, deadline=None)
@given(graphs(), st.integers(min_value=1, max_value=4))
def test_max_depth_is_exact(adj: Adj, max_depth: int) -> None:
    s, t = endpoints(adj)
    expected = nx_hops(to_nx(adj), s, t)
    reachable = expected is not None and expected <= max_depth
    for search in (alg.bfs_path, alg.bidirectional_bfs_path):
        result = search(adj, s, t, max_depth=max_depth)
        assert (result.path is not None) == reachable


@settings(max_examples=150, deadline=None)
@given(graphs())
def test_dijkstra_matches_networkx_cost(adj: Adj) -> None:
    s, t = endpoints(adj)
    graph = to_nx(adj)
    result = alg.dijkstra_path(adj, s, t)
    if not nx.has_path(graph, s, t):
        assert result.path is None
        return
    assert result.path is not None
    assert is_valid_path(adj, result.path)
    assert result.cost == pytest.approx(nx.dijkstra_path_length(graph, s, t, weight="cost"))


@settings(max_examples=100, deadline=None)
@given(graphs(max_nodes=9), st.integers(min_value=1, max_value=4))
def test_dijkstra_hop_limit_is_cheapest_within_limit(adj: Adj, max_depth: int) -> None:
    s, t = endpoints(adj)
    graph = to_nx(adj)
    within = [
        sum(graph[a][b]["cost"] for a, b in itertools.pairwise(p))
        for p in nx.all_simple_paths(graph, s, t, cutoff=max_depth)
    ]
    result = alg.dijkstra_path(adj, s, t, max_depth=max_depth)
    if not within:
        assert result.path is None
    else:
        assert result.path is not None
        assert len(result.path) - 1 <= max_depth
        assert result.cost == pytest.approx(min(within))


@settings(max_examples=100, deadline=None)
@given(graphs(max_nodes=10), st.integers(min_value=1, max_value=4))
def test_yen_returns_the_k_shortest_simple_paths(adj: Adj, k: int) -> None:
    s, t = endpoints(adj)
    graph = to_nx(adj)
    paths = alg.yen_k_shortest_paths(adj, s, t, k)
    if not nx.has_path(graph, s, t):
        assert paths == []
        return
    expected = []
    for path in nx.shortest_simple_paths(graph, s, t):
        expected.append(len(path) - 1)
        if len(expected) == k:
            break
    assert [len(p) - 1 for p in paths] == expected
    assert len(set(paths)) == len(paths)
    assert all(is_valid_path(adj, p) for p in paths)


@settings(max_examples=100, deadline=None)
@given(graphs())
def test_bfs_distances_match_networkx(adj: Adj) -> None:
    sources = sorted(adj)[:2]
    expected = nx.multi_source_dijkstra_path_length(to_nx(adj), set(sources), weight=None)
    assert alg.bfs_distances(adj, sources) == expected


@settings(max_examples=60, deadline=None)
@given(graphs())
def test_pagerank_matches_networkx(adj: Adj) -> None:
    expected = nx.pagerank(to_nx(adj), weight="weight", tol=1e-12, max_iter=1000)
    actual = alg.pagerank(adj, tol=1e-12, max_iter=1000)
    assert actual == pytest.approx(expected, abs=1e-6)
    assert sum(actual.values()) == pytest.approx(1.0)


@settings(max_examples=60, deadline=None)
@given(graphs())
def test_betweenness_matches_networkx(adj: Adj) -> None:
    expected = nx.betweenness_centrality(to_nx(adj), normalized=True)
    assert alg.betweenness(adj) == pytest.approx(expected, abs=1e-9)


@settings(max_examples=60, deadline=None)
@given(graphs())
def test_components_match_networkx(adj: Adj) -> None:
    expected = {frozenset(c) for c in nx.connected_components(to_nx(adj))}
    components = alg.connected_components(adj)
    assert set(components) == expected
    assert [len(c) for c in components] == sorted((len(c) for c in components), reverse=True)


def test_sampled_betweenness_is_reproducible() -> None:
    adj: Adj = {f"n{i}": {} for i in range(30)}
    for i in range(29):
        adj[f"n{i}"][f"n{i + 1}"] = adj[f"n{i + 1}"][f"n{i}"] = 1.0
    first = alg.betweenness(adj, sample_size=10, seed=7)
    assert first == alg.betweenness(adj, sample_size=10, seed=7)


def test_expansion_budget_reports_truncation() -> None:
    adj: Adj = {f"n{i:03d}": {} for i in range(200)}
    for i in range(199):
        adj[f"n{i:03d}"][f"n{i + 1:03d}"] = adj[f"n{i + 1:03d}"][f"n{i:03d}"] = 1.0
    for search in (alg.bfs_path, alg.bidirectional_bfs_path, alg.dijkstra_path):
        result = search(adj, "n000", "n199", max_expansions=20)
        assert result.path is None
        assert result.truncated


def test_ties_are_broken_by_node_id() -> None:
    # Two equally short routes: through "a" and through "b".
    adj: Adj = {
        "s": {"b": 1, "a": 1},
        "a": {"s": 1, "t": 1},
        "b": {"s": 1, "t": 1},
        "t": {"a": 1, "b": 1},
    }
    assert alg.bfs_path(adj, "s", "t").path == ("s", "a", "t")
    assert alg.bidirectional_bfs_path(adj, "s", "t").path == ("s", "a", "t")
    assert alg.dijkstra_path(adj, "s", "t").path == ("s", "a", "t")


def test_unknown_and_identical_endpoints() -> None:
    adj: Adj = {"a": {}}
    assert alg.bfs_path(adj, "a", "missing").path is None
    assert alg.bidirectional_bfs_path(adj, "a", "a").path == ("a",)
