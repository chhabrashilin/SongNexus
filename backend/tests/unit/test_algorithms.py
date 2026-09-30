"""Graph algorithms, property-tested against networkx as an oracle."""

from __future__ import annotations

import math
from itertools import pairwise

import networkx as nx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from songnexus.graph import algorithms as alg

Adj = dict[str, dict[str, float]]


@st.composite
def graphs(draw: st.DrawFn, max_nodes: int = 14) -> Adj:
    n = draw(st.integers(min_value=2, max_value=max_nodes))
    nodes = [f"n{i:02d}" for i in range(n)]
    adj: Adj = {v: {} for v in nodes}
    pairs = [(nodes[i], nodes[j]) for i in range(n) for j in range(i + 1, n)]
    chosen = draw(st.lists(st.sampled_from(pairs), max_size=min(len(pairs), 3 * n), unique=True))
    for u, v in chosen:
        w = draw(st.sampled_from([0.25, 0.5, 1.0, 2.0, 3.0]))
        adj[u][v] = adj[v][u] = w
    return adj


def to_nx(adj: Adj) -> nx.Graph:
    g = nx.Graph()
    g.add_nodes_from(adj)
    for u, nbrs in adj.items():
        for v, w in nbrs.items():
            g.add_edge(u, v, strength=w, cost=1.0 / w)
    return g


def is_valid_path(adj: Adj, path: list[str]) -> bool:
    return len(set(path)) == len(path) and all(v in adj[u] for u, v in pairwise(path))


@settings(max_examples=200, deadline=None)
@given(graphs(), st.data())
def test_bfs_and_bidirectional_match_networkx_lengths(adj: Adj, data: st.DataObject) -> None:
    nodes = sorted(adj)
    s = data.draw(st.sampled_from(nodes))
    t = data.draw(st.sampled_from(nodes))
    g = to_nx(adj)
    expected = nx.shortest_path_length(g, s, t) if nx.has_path(g, s, t) else None

    for result in (alg.bfs_path(adj, s, t), alg.bidirectional_bfs_path(adj, s, t)):
        if expected is None:
            assert result.path is None
        else:
            assert result.path is not None
            assert result.path[0] == s and result.path[-1] == t
            assert len(result.path) - 1 == expected
            assert is_valid_path(adj, result.path)


@settings(max_examples=150, deadline=None)
@given(graphs(), st.data(), st.integers(min_value=1, max_value=4))
def test_max_depth_is_respected(adj: Adj, data: st.DataObject, depth: int) -> None:
    nodes = sorted(adj)
    s, t = data.draw(st.sampled_from(nodes)), data.draw(st.sampled_from(nodes))
    g = to_nx(adj)
    reachable = nx.has_path(g, s, t) and nx.shortest_path_length(g, s, t) <= depth
    for result in (
        alg.bfs_path(adj, s, t, depth),
        alg.bidirectional_bfs_path(adj, s, t, depth),
        alg.dijkstra_path(adj, s, t, max_depth=depth),
    ):
        assert (result.path is not None) == reachable
        if result.path is not None:
            assert len(result.path) - 1 <= depth


@settings(max_examples=200, deadline=None)
@given(graphs(), st.data())
def test_dijkstra_matches_networkx_cost(adj: Adj, data: st.DataObject) -> None:
    nodes = sorted(adj)
    s, t = data.draw(st.sampled_from(nodes)), data.draw(st.sampled_from(nodes))
    g = to_nx(adj)
    result = alg.dijkstra_path(adj, s, t)
    if not nx.has_path(g, s, t):
        assert result.path is None
        return
    expected = nx.dijkstra_path_length(g, s, t, weight="cost")
    assert result.path is not None and result.cost is not None
    assert math.isclose(result.cost, expected, rel_tol=1e-9)
    assert is_valid_path(adj, result.path)


@settings(max_examples=100, deadline=None)
@given(graphs(max_nodes=10), st.data(), st.integers(min_value=1, max_value=5))
def test_yen_matches_networkx_simple_path_lengths(adj: Adj, data: st.DataObject, k: int) -> None:
    nodes = sorted(adj)
    s, t = data.draw(st.sampled_from(nodes)), data.draw(st.sampled_from(nodes))
    if s == t:
        return
    g = to_nx(adj)
    ours = alg.yen_k_shortest_paths(adj, s, t, k)
    if not nx.has_path(g, s, t):
        assert ours == []
        return
    expected = [len(p) - 1 for _, p in zip(range(k), nx.shortest_simple_paths(g, s, t), strict=False)]
    assert [len(p) - 1 for p in ours] == expected
    assert len({tuple(p) for p in ours}) == len(ours)
    assert all(is_valid_path(adj, p) and p[0] == s and p[-1] == t for p in ours)


@settings(max_examples=100, deadline=None)
@given(graphs())
def test_pagerank_matches_networkx(adj: Adj) -> None:
    ours = alg.pagerank(adj)
    theirs = nx.pagerank(to_nx(adj), alpha=0.85, weight="strength", tol=1e-12, max_iter=1000)
    assert math.isclose(sum(ours.values()), 1.0, rel_tol=1e-9)
    for node in adj:
        assert math.isclose(ours[node], theirs[node], abs_tol=1e-6)


@settings(max_examples=100, deadline=None)
@given(graphs())
def test_exact_betweenness_matches_networkx(adj: Adj) -> None:
    ours = alg.betweenness(adj, normalized=True)
    theirs = nx.betweenness_centrality(to_nx(adj), normalized=True)
    for node in adj:
        assert math.isclose(ours[node], theirs[node], abs_tol=1e-9)


def test_sampled_betweenness_is_reproducible_and_ranks_the_bridge_first() -> None:
    # Two cliques joined through a single bridge node.
    adj: Adj = {}
    left = [f"l{i}" for i in range(6)]
    right = [f"r{i}" for i in range(6)]
    for group in (left, right):
        for u in group:
            adj.setdefault(u, {})
            for v in group:
                if u != v:
                    adj[u][v] = 1.0
    adj["bridge"] = {"l0": 1.0, "r0": 1.0}
    adj["l0"]["bridge"] = adj["r0"]["bridge"] = 1.0
    a = alg.betweenness(adj, sample_size=6, seed=3)
    b = alg.betweenness(adj, sample_size=6, seed=3)
    assert a == b
    assert max(a, key=lambda n: a[n]) in {"bridge", "l0", "r0"}


@settings(max_examples=100, deadline=None)
@given(graphs())
def test_components_match_networkx(adj: Adj) -> None:
    ours = sorted(sorted(c) for c in alg.connected_components(adj))
    theirs = sorted(sorted(c) for c in nx.connected_components(to_nx(adj)))
    assert ours == theirs


def test_degree_measures() -> None:
    adj: Adj = {"a": {"b": 2.0, "c": 1.0}, "b": {"a": 2.0}, "c": {"a": 1.0}}
    assert alg.degree(adj) == {"a": 2.0, "b": 1.0, "c": 1.0}
    assert alg.weighted_degree(adj) == {"a": 3.0, "b": 2.0, "c": 1.0}


def test_bidirectional_expands_fewer_nodes_on_a_long_chain_with_branches() -> None:
    adj: Adj = {}

    def link(u: str, v: str) -> None:
        adj.setdefault(u, {})[v] = 1.0
        adj.setdefault(v, {})[u] = 1.0

    chain = [f"c{i:02d}" for i in range(12)]
    for u, v in pairwise(chain):
        link(u, v)
    for node in chain:  # bushy side branches inflate unidirectional search
        for j in range(5):
            link(node, f"{node}-leaf{j}")
    uni = alg.bfs_path(adj, chain[0], chain[-1])
    bi = alg.bidirectional_bfs_path(adj, chain[0], chain[-1])
    assert uni.path == bi.path
    assert bi.expanded < uni.expanded


@pytest.mark.parametrize("fn", [alg.bfs_path, alg.bidirectional_bfs_path, alg.dijkstra_path])
def test_unknown_nodes_return_no_path(fn) -> None:  # type: ignore[no-untyped-def]
    adj: Adj = {"a": {"b": 1.0}, "b": {"a": 1.0}}
    assert fn(adj, "a", "zzz").path is None
    assert fn(adj, "a", "a").path == ["a"]


@settings(max_examples=100, deadline=None)
@given(graphs(), st.data())
def test_bfs_distances_match_networkx(adj: Adj, data: st.DataObject) -> None:
    source = data.draw(st.sampled_from(sorted(adj)))
    assert alg.bfs_distances(adj, source) == nx.single_source_shortest_path_length(to_nx(adj), source)
    capped = alg.bfs_distances(adj, source, max_depth=2)
    assert all(d <= 2 for d in capped.values())
