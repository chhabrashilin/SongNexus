"""Graph algorithms over an undirected weighted adjacency mapping.

All functions take ``adj: Mapping[node, Mapping[neighbor, weight]]`` where
weight is a positive *strength* (larger = stronger connection). They are pure,
deterministic (ties broken by node ID), and independent of the music domain,
so they are property-tested against networkx (tests/unit/test_algorithms.py).

Complexities use V = nodes, E = edges, d = path length, b = branching factor.
"""

from __future__ import annotations

import heapq
import random
from collections import deque
from collections.abc import Callable, Hashable, Iterable, Mapping
from dataclasses import dataclass
from typing import TypeVar

N = TypeVar("N", bound=Hashable)
Adjacency = Mapping[N, Mapping[N, float]]


@dataclass(frozen=True)
class PathResult:
    path: list[str] | None
    cost: float | None = None
    expanded: int = 0  # nodes dequeued; used by benchmarks to compare strategies


def _sorted_neighbors(adj: Adjacency[str], node: str) -> list[str]:
    return sorted(adj.get(node, {}))


def _reconstruct(parents: Mapping[str, str | None], end: str) -> list[str]:
    path = [end]
    while (parent := parents[path[-1]]) is not None:
        path.append(parent)
    path.reverse()
    return path


# ---------------------------------------------------------------------------
# Shortest paths
# ---------------------------------------------------------------------------


def bfs_path(
    adj: Adjacency[str],
    source: str,
    target: str,
    max_depth: int | None = None,
    banned_nodes: frozenset[str] = frozenset(),
    banned_edges: frozenset[tuple[str, str]] = frozenset(),
) -> PathResult:
    """Unweighted shortest path by breadth-first search. O(V + E).

    ``banned_*`` support Yen's algorithm; banned edges are directed pairs.
    """
    if source not in adj or target not in adj or source in banned_nodes:
        return PathResult(None)
    if source == target:
        return PathResult([source], 0.0, 1)
    parents: dict[str, str | None] = {source: None}
    depth = {source: 0}
    queue = deque([source])
    expanded = 0
    while queue:
        node = queue.popleft()
        expanded += 1
        if max_depth is not None and depth[node] >= max_depth:
            continue
        for nbr in _sorted_neighbors(adj, node):
            if nbr in parents or nbr in banned_nodes or (node, nbr) in banned_edges:
                continue
            parents[nbr] = node
            depth[nbr] = depth[node] + 1
            if nbr == target:
                path = _reconstruct(parents, target)
                return PathResult(path, float(len(path) - 1), expanded)
            queue.append(nbr)
    return PathResult(None, None, expanded)


def bfs_distances(adj: Adjacency[str], source: str, max_depth: int | None = None) -> dict[str, int]:
    """Hop distance from ``source`` to every reachable node (single-source BFS). O(V + E)."""
    if source not in adj:
        return {}
    dist = {source: 0}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        if max_depth is not None and dist[node] >= max_depth:
            continue
        for nbr in adj[node]:
            if nbr not in dist:
                dist[nbr] = dist[node] + 1
                queue.append(nbr)
    return dist


def bidirectional_bfs_path(adj: Adjacency[str], source: str, target: str, max_depth: int | None = None) -> PathResult:
    """Unweighted shortest path searching from both ends. O(b^(d/2)) vs O(b^d).

    Always expands the smaller frontier one full level at a time, and among all
    meeting points of that level picks the one minimizing total length (then by
    node ID), which guarantees an optimal and deterministic result.
    """
    if source not in adj or target not in adj:
        return PathResult(None)
    if source == target:
        return PathResult([source], 0.0, 1)
    parents_f: dict[str, str | None] = {source: None}
    parents_b: dict[str, str | None] = {target: None}
    dist_f, dist_b = {source: 0}, {target: 0}
    frontier_f, frontier_b = [source], [target]
    expanded = 0

    while frontier_f and frontier_b:
        if max_depth is not None and (max(dist_f.values()) + max(dist_b.values())) >= max_depth:
            break
        forward = len(frontier_f) <= len(frontier_b)
        frontier, parents, dist, other_dist = (
            (frontier_f, parents_f, dist_f, dist_b) if forward else (frontier_b, parents_b, dist_b, dist_f)
        )
        next_frontier: list[str] = []
        meetings: list[tuple[int, str]] = []
        for node in frontier:
            expanded += 1
            for nbr in _sorted_neighbors(adj, node):
                if nbr in parents:
                    continue
                parents[nbr] = node
                dist[nbr] = dist[node] + 1
                next_frontier.append(nbr)
                if nbr in other_dist:
                    meetings.append((dist[nbr] + other_dist[nbr], nbr))
        if meetings:
            _, meet = min(meetings)
            forward_half = _reconstruct(parents_f, meet)
            backward_half = _reconstruct(parents_b, meet)[::-1]
            path = forward_half + backward_half[1:]
            if max_depth is not None and len(path) - 1 > max_depth:
                return PathResult(None, None, expanded)
            return PathResult(path, float(len(path) - 1), expanded)
        if forward:
            frontier_f = next_frontier
        else:
            frontier_b = next_frontier
    return PathResult(None, None, expanded)


def strength_to_cost(strength: float) -> float:
    """Dijkstra edge cost for a connection strength: stronger = cheaper.

    1/strength keeps costs positive and makes a single very strong link cheaper
    than a chain of weak ones. A one-hop path always costs <= 1 / min_strength.
    """
    return 1.0 / strength


def dijkstra_path(
    adj: Adjacency[str],
    source: str,
    target: str,
    cost: Callable[[float], float] = strength_to_cost,
    max_depth: int | None = None,
) -> PathResult:
    """Minimum-cost path. O((V + E) log V) with a binary heap.

    With ``max_depth``, states are (node, hops) so the hop limit is exact.
    """
    if source not in adj or target not in adj:
        return PathResult(None)
    best: dict[tuple[str, int], float] = {(source, 0): 0.0}
    parents: dict[tuple[str, int], tuple[str, int] | None] = {(source, 0): None}
    heap: list[tuple[float, int, str]] = [(0.0, 0, source)]
    settled: set[str] = set()
    expanded = 0
    while heap:
        dist, hops, node = heapq.heappop(heap)
        if dist > best.get((node, hops), float("inf")):
            continue
        if max_depth is None and node in settled:
            continue
        settled.add(node)
        expanded += 1
        if node == target:
            path = []
            state: tuple[str, int] | None = (node, hops)
            while state is not None:
                path.append(state[0])
                state = parents[state]
            return PathResult(path[::-1], dist, expanded)
        if max_depth is not None and hops >= max_depth:
            continue
        for nbr in _sorted_neighbors(adj, node):
            nhops = hops + 1 if max_depth is not None else 0
            key = (nbr, nhops)
            candidate = dist + cost(adj[node][nbr])
            if candidate < best.get(key, float("inf")):
                best[key] = candidate
                parents[key] = (node, hops)
                heapq.heappush(heap, (candidate, nhops, nbr))
    return PathResult(None, None, expanded)


def yen_k_shortest_paths(
    adj: Adjacency[str], source: str, target: str, k: int, max_depth: int | None = None
) -> list[list[str]]:
    """k loopless shortest paths (by hop count), Yen's algorithm.

    O(k * V * (V + E)) worst case; in practice bounded by the small ``k`` the
    API allows. Paths are returned shortest first, ties ordered by node IDs.
    """
    first = bfs_path(adj, source, target, max_depth)
    if first.path is None:
        return []
    accepted: list[list[str]] = [first.path]
    candidates: list[tuple[int, list[str]]] = []
    seen = {tuple(first.path)}
    while len(accepted) < k:
        last = accepted[-1]
        for i in range(len(last) - 1):
            spur, root = last[i], last[: i + 1]
            banned_edges = {(p[i], p[i + 1]) for p in accepted if len(p) > i + 1 and p[: i + 1] == root}
            banned_nodes = frozenset(root[:-1])
            remaining = None if max_depth is None else max_depth - i
            spur_result = bfs_path(adj, spur, target, remaining, banned_nodes, frozenset(banned_edges))
            if spur_result.path is None:
                continue
            candidate = root[:-1] + spur_result.path
            if tuple(candidate) not in seen:
                seen.add(tuple(candidate))
                heapq.heappush(candidates, (len(candidate), candidate))
        if not candidates:
            break
        accepted.append(heapq.heappop(candidates)[1])
    return accepted


# ---------------------------------------------------------------------------
# Centrality and structure
# ---------------------------------------------------------------------------


def weighted_degree(adj: Adjacency[str]) -> dict[str, float]:
    return {node: float(sum(nbrs.values())) for node, nbrs in adj.items()}


def degree(adj: Adjacency[str]) -> dict[str, float]:
    return {node: float(len(nbrs)) for node, nbrs in adj.items()}


def pagerank(adj: Adjacency[str], damping: float = 0.85, tol: float = 1e-10, max_iter: int = 200) -> dict[str, float]:
    """Weighted PageRank by power iteration. O(iterations * (V + E)).

    Rank flows along edges proportionally to strength. Dangling nodes (no
    edges) redistribute their rank uniformly, so scores always sum to 1.
    """
    nodes = sorted(adj)
    n = len(nodes)
    if n == 0:
        return {}
    out_weight = {u: sum(adj[u].values()) for u in nodes}
    rank = dict.fromkeys(nodes, 1.0 / n)
    for _ in range(max_iter):
        dangling = sum(rank[u] for u in nodes if out_weight[u] == 0)
        base = (1.0 - damping) / n + damping * dangling / n
        new = dict.fromkeys(nodes, base)
        for u in nodes:
            if out_weight[u] == 0:
                continue
            share = damping * rank[u] / out_weight[u]
            for v, w in adj[u].items():
                new[v] += share * w
        delta = sum(abs(new[u] - rank[u]) for u in nodes)
        rank = new
        if delta < n * tol:
            break
    return rank


def betweenness(
    adj: Adjacency[str],
    normalized: bool = True,
    sample_size: int | None = None,
    seed: int = 0,
) -> dict[str, float]:
    """Unweighted betweenness centrality, Brandes' algorithm. O(V * E).

    With ``sample_size`` < V, uses k random pivot sources and scales the result
    (Brandes & Pich 2007), trading exactness for O(k * E) time. The seed makes
    sampled results reproducible.
    """
    nodes = sorted(adj)
    n = len(nodes)
    scores = dict.fromkeys(nodes, 0.0)
    sources: Iterable[str] = nodes
    if sample_size is not None and sample_size < n:
        sources = random.Random(seed).sample(nodes, sample_size)
    num_sources = 0
    for s in sources:
        num_sources += 1
        stack: list[str] = []
        preds: dict[str, list[str]] = {v: [] for v in nodes}
        sigma = dict.fromkeys(nodes, 0.0)
        sigma[s] = 1.0
        dist = dict.fromkeys(nodes, -1)
        dist[s] = 0
        queue = deque([s])
        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in adj[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    queue.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    preds[w].append(v)
        delta = dict.fromkeys(nodes, 0.0)
        while stack:
            w = stack.pop()
            for v in preds[w]:
                delta[v] += sigma[v] / sigma[w] * (1.0 + delta[w])
            if w != s:
                scores[w] += delta[w]
    # Undirected graph: each pair counted from both endpoints.
    scale = 0.5
    if num_sources and num_sources < n:
        scale *= n / num_sources
    if normalized and n > 2:
        scale *= 2.0 / ((n - 1) * (n - 2))
    return {v: s * scale for v, s in scores.items()}


def connected_components(adj: Adjacency[str]) -> list[set[str]]:
    """Components, largest first. O(V + E)."""
    seen: set[str] = set()
    components: list[set[str]] = []
    for start in sorted(adj):
        if start in seen:
            continue
        component = {start}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for nbr in adj[node]:
                if nbr not in component:
                    component.add(nbr)
                    queue.append(nbr)
        seen |= component
        components.append(component)
    components.sort(key=lambda c: (-len(c), min(c)))
    return components
