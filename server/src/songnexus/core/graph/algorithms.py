"""Graph algorithms over an undirected, weighted adjacency mapping.

Every function takes ``adj: Mapping[node, Mapping[neighbor, strength]]``, where
strength is positive and larger means a stronger connection. The functions are
pure, deterministic (ties broken by node ID) and independent of music, so they
are property-tested against networkx.

Node predicates (``allowed``) restrict which nodes a search may pass through.
The endpoints of a path search are always permitted (the caller decides whether
the endpoints themselves are acceptable), so a genre filter or a block list
applies inside the search, not after it. A filtered-out node is never on a
returned path.

Searches that could be expensive take ``max_expansions``. When the budget runs
out the result says so (``truncated``), so callers can report "not found within
the search limit" rather than "not connected".

Complexities use V nodes, E edges, d path length and b branching factor.
"""

from __future__ import annotations

import heapq
import random
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

Adjacency = Mapping[str, Mapping[str, float]]
NodePredicate = Callable[[str], bool]

DEFAULT_MAX_EXPANSIONS = 50_000


@dataclass(frozen=True)
class PathResult:
    """The outcome of a path search.

    Attributes:
        path: The nodes from source to target, or None when none was found.
        cost: Hop count (BFS) or summed edge cost (Dijkstra); None without a path.
        expanded: Nodes expanded, for benchmarks and budget accounting.
        truncated: True when the search stopped at its expansion budget, so the
            absence of a path is not conclusive.
    """

    path: tuple[str, ...] | None
    cost: float | None = None
    expanded: int = 0
    truncated: bool = False


def _permits(allowed: NodePredicate | None, node: str, *endpoints: str) -> bool:
    return allowed is None or node in endpoints or allowed(node)


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
    adj: Adjacency,
    source: str,
    target: str,
    *,
    max_depth: int | None = None,
    allowed: NodePredicate | None = None,
    banned_nodes: frozenset[str] = frozenset(),
    banned_edges: frozenset[tuple[str, str]] = frozenset(),
    max_expansions: int = DEFAULT_MAX_EXPANSIONS,
) -> PathResult:
    """Finds an unweighted shortest path by breadth-first search. O(V + E).

    ``banned_nodes`` and ``banned_edges`` (directed pairs) support Yen's algorithm.
    """
    if source not in adj or target not in adj or source in banned_nodes:
        return PathResult(None)
    if source == target:
        return PathResult((source,), 0.0, 1)
    parents: dict[str, str | None] = {source: None}
    depth = {source: 0}
    queue = deque([source])
    expanded = 0
    while queue:
        if expanded >= max_expansions:
            return PathResult(None, None, expanded, truncated=True)
        node = queue.popleft()
        expanded += 1
        if max_depth is not None and depth[node] >= max_depth:
            continue
        for neighbor in sorted(adj[node]):
            if (
                neighbor in parents
                or neighbor in banned_nodes
                or (node, neighbor) in banned_edges
                or not _permits(allowed, neighbor, target)
            ):
                continue
            parents[neighbor] = node
            depth[neighbor] = depth[node] + 1
            if neighbor == target:
                path = _reconstruct(parents, target)
                return PathResult(tuple(path), float(len(path) - 1), expanded)
            queue.append(neighbor)
    return PathResult(None, None, expanded)


@dataclass
class _Side:
    """One direction of a bidirectional search."""

    frontier: list[str]
    parents: dict[str, str | None]
    dist: dict[str, int]


def _expand_level(
    adj: Adjacency,
    side: _Side,
    other_dist: Mapping[str, int],
    *,
    allowed: NodePredicate | None,
    endpoints: tuple[str, str],
    budget: int,
) -> tuple[list[str] | None, list[tuple[int, str]], int]:
    """Expands one full BFS level of ``side``.

    Returns:
        The next frontier (None when the budget ran out), every meeting with the
        other side as (total length, node), and the number of nodes expanded.
    """
    next_frontier: list[str] = []
    meetings: list[tuple[int, str]] = []
    for used, node in enumerate(side.frontier):
        if used >= budget:
            return None, meetings, used
        for neighbor in sorted(adj[node]):
            if neighbor in side.parents or not _permits(allowed, neighbor, *endpoints):
                continue
            side.parents[neighbor] = node
            side.dist[neighbor] = side.dist[node] + 1
            next_frontier.append(neighbor)
            if neighbor in other_dist:
                meetings.append((side.dist[neighbor] + other_dist[neighbor], neighbor))
    return next_frontier, meetings, len(side.frontier)


def bidirectional_bfs_path(
    adj: Adjacency,
    source: str,
    target: str,
    *,
    max_depth: int | None = None,
    allowed: NodePredicate | None = None,
    max_expansions: int = DEFAULT_MAX_EXPANSIONS,
) -> PathResult:
    """Finds an unweighted shortest path by searching from both ends. O(b^(d/2)).

    Expands the smaller frontier one full level at a time. Among all meetings
    found in that level it picks the shortest total (then the smallest meeting
    node ID), which makes the result both optimal and deterministic.
    """
    if source not in adj or target not in adj:
        return PathResult(None)
    if source == target:
        return PathResult((source,), 0.0, 1)
    parents_fwd: dict[str, str | None] = {source: None}
    parents_bwd: dict[str, str | None] = {target: None}
    dist_fwd, dist_bwd = {source: 0}, {target: 0}
    frontier_fwd, frontier_bwd = [source], [target]
    level_fwd = level_bwd = 0
    expanded = 0

    while frontier_fwd and frontier_bwd:
        # Any meeting from here on is at least level_fwd + level_bwd + 1 long.
        if max_depth is not None and level_fwd + level_bwd >= max_depth:
            break
        forward = len(frontier_fwd) <= len(frontier_bwd)
        side = (
            _Side(frontier_fwd, parents_fwd, dist_fwd)
            if forward
            else _Side(frontier_bwd, parents_bwd, dist_bwd)
        )
        other = dist_bwd if forward else dist_fwd
        budget = max_expansions - expanded
        next_frontier, meetings, used = _expand_level(
            adj, side, other, allowed=allowed, endpoints=(source, target), budget=budget
        )
        expanded += used
        if next_frontier is None:
            return PathResult(None, None, expanded, truncated=True)
        if meetings:
            total, meet = min(meetings)
            if max_depth is not None and total > max_depth:
                return PathResult(None, None, expanded)
            path = _reconstruct(parents_fwd, meet) + _reconstruct(parents_bwd, meet)[::-1][1:]
            return PathResult(tuple(path), float(total), expanded)
        if forward:
            frontier_fwd, level_fwd = next_frontier, level_fwd + 1
        else:
            frontier_bwd, level_bwd = next_frontier, level_bwd + 1
    return PathResult(None, None, expanded)


def strength_to_cost(strength: float) -> float:
    """Returns the Dijkstra edge cost of a connection strength: stronger is cheaper.

    ``1 / strength`` keeps costs positive and makes one very strong link cheaper
    than a chain of weak ones.
    """
    return 1.0 / strength


def dijkstra_path(
    adj: Adjacency,
    source: str,
    target: str,
    *,
    cost: Callable[[float], float] = strength_to_cost,
    max_depth: int | None = None,
    allowed: NodePredicate | None = None,
    max_expansions: int = DEFAULT_MAX_EXPANSIONS,
) -> PathResult:
    """Finds a minimum-cost path. O((V + E) log V) with a binary heap.

    With ``max_depth`` the search state is (node, hops), so the hop limit is
    exact: the result is the cheapest path among those with at most
    ``max_depth`` edges.
    """
    if source not in adj or target not in adj:
        return PathResult(None)
    best: dict[tuple[str, int], float] = {(source, 0): 0.0}
    parents: dict[tuple[str, int], tuple[str, int] | None] = {(source, 0): None}
    heap: list[tuple[float, int, str]] = [(0.0, 0, source)]
    settled: set[tuple[str, int]] = set()
    expanded = 0
    while heap:
        distance, hops, node = heapq.heappop(heap)
        state = (node, hops)
        if state in settled:
            continue
        if expanded >= max_expansions:
            return PathResult(None, None, expanded, truncated=True)
        settled.add(state)
        expanded += 1
        if node == target:
            path: list[str] = []
            cursor: tuple[str, int] | None = state
            while cursor is not None:
                path.append(cursor[0])
                cursor = parents[cursor]
            return PathResult(tuple(reversed(path)), distance, expanded)
        if max_depth is not None and hops >= max_depth:
            continue
        for neighbor in sorted(adj[node]):
            if not _permits(allowed, neighbor, target):
                continue
            # Without a hop limit every state collapses to hop 0 (plain Dijkstra).
            next_state = (neighbor, hops + 1 if max_depth is not None else 0)
            candidate = distance + cost(adj[node][neighbor])
            if candidate < best.get(next_state, float("inf")):
                best[next_state] = candidate
                parents[next_state] = state
                heapq.heappush(heap, (candidate, next_state[1], neighbor))
    return PathResult(None, None, expanded)


def yen_k_shortest_paths(
    adj: Adjacency,
    source: str,
    target: str,
    k: int,
    *,
    max_depth: int | None = None,
    allowed: NodePredicate | None = None,
    max_expansions: int = DEFAULT_MAX_EXPANSIONS,
) -> list[tuple[str, ...]]:
    """Returns up to ``k`` loopless shortest paths by hop count (Yen's algorithm).

    O(k * V * (V + E)) in the worst case, bounded in practice by the small ``k``
    the API allows. Paths come shortest first, ties ordered by node IDs. The
    expansion budget is shared by all spur searches.
    """
    budget = max_expansions
    first = bfs_path(
        adj, source, target, max_depth=max_depth, allowed=allowed, max_expansions=budget
    )
    budget -= first.expanded
    if first.path is None:
        return []
    accepted: list[tuple[str, ...]] = [first.path]
    candidates: list[tuple[int, tuple[str, ...]]] = []
    seen = {first.path}
    while len(accepted) < k and budget > 0:
        last = accepted[-1]
        for i in range(len(last) - 1):
            spur, root = last[i], last[: i + 1]
            banned_edges = frozenset(
                (p[i], p[i + 1]) for p in accepted if len(p) > i + 1 and p[: i + 1] == root
            )
            remaining = None if max_depth is None else max_depth - i
            spur_result = bfs_path(
                adj,
                spur,
                target,
                max_depth=remaining,
                allowed=allowed,
                banned_nodes=frozenset(root[:-1]),
                banned_edges=banned_edges,
                max_expansions=max(budget, 0),
            )
            budget -= spur_result.expanded
            if spur_result.path is None:
                continue
            candidate = root[:-1] + spur_result.path
            if candidate not in seen:
                seen.add(candidate)
                heapq.heappush(candidates, (len(candidate), candidate))
        if not candidates:
            break
        accepted.append(heapq.heappop(candidates)[1])
    return accepted


# ---------------------------------------------------------------------------
# Neighborhoods
# ---------------------------------------------------------------------------


def bfs_distances(
    adj: Adjacency,
    sources: str | Iterable[str],
    *,
    max_depth: int | None = None,
    allowed: NodePredicate | None = None,
) -> dict[str, int]:
    """Returns hop distances from the nearest source to every reachable node. O(V + E).

    Accepts one source or several (multi-source BFS). Sources are always
    included; other nodes must satisfy ``allowed``.
    """
    starts = [sources] if isinstance(sources, str) else sorted(set(sources))
    distances = {s: 0 for s in starts if s in adj}
    queue = deque(distances)
    while queue:
        node = queue.popleft()
        if max_depth is not None and distances[node] >= max_depth:
            continue
        for neighbor in sorted(adj[node]):
            if neighbor not in distances and _permits(allowed, neighbor):
                distances[neighbor] = distances[node] + 1
                queue.append(neighbor)
    return distances


def connected_components(adj: Adjacency) -> list[frozenset[str]]:
    """Returns connected components, largest first (ties by smallest node). O(V + E)."""
    seen: set[str] = set()
    components: list[frozenset[str]] = []
    for start in sorted(adj):
        if start in seen:
            continue
        component = frozenset(bfs_distances(adj, start))
        seen |= component
        components.append(component)
    components.sort(key=lambda c: (-len(c), min(c)))
    return components


# ---------------------------------------------------------------------------
# Centrality
# ---------------------------------------------------------------------------


def weighted_degree(adj: Adjacency) -> dict[str, float]:
    """Returns each node's summed edge strength."""
    return {node: float(sum(neighbors.values())) for node, neighbors in adj.items()}


def pagerank(
    adj: Adjacency, *, damping: float = 0.85, tol: float = 1e-10, max_iter: int = 200
) -> dict[str, float]:
    """Returns weighted PageRank by power iteration. O(iterations * (V + E)).

    Rank flows along edges in proportion to strength. Dangling nodes redistribute
    their rank uniformly, so scores always sum to 1.
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
        updated = dict.fromkeys(nodes, base)
        for u in nodes:
            if out_weight[u] == 0:
                continue
            share = damping * rank[u] / out_weight[u]
            for v, weight in adj[u].items():
                updated[v] += share * weight
        delta = sum(abs(updated[u] - rank[u]) for u in nodes)
        rank = updated
        if delta < n * tol:
            break
    return rank


def betweenness(
    adj: Adjacency, *, normalized: bool = True, sample_size: int | None = None, seed: int = 0
) -> dict[str, float]:
    """Returns unweighted betweenness centrality (Brandes' algorithm). O(V * E).

    With ``sample_size`` below V, uses that many random pivot sources and
    rescales (Brandes and Pich, 2007), for O(k * E) time. The seed makes sampled
    results reproducible.
    """
    nodes = sorted(adj)
    n = len(nodes)
    scores = dict.fromkeys(nodes, 0.0)
    sources: list[str] = nodes
    if sample_size is not None and sample_size < n:
        sources = random.Random(seed).sample(nodes, sample_size)  # noqa: S311 - not security
    for s in sources:
        stack: list[str] = []
        predecessors: dict[str, list[str]] = {v: [] for v in nodes}
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
                    predecessors[w].append(v)
        delta = dict.fromkeys(nodes, 0.0)
        while stack:
            w = stack.pop()
            for v in predecessors[w]:
                delta[v] += sigma[v] / sigma[w] * (1.0 + delta[w])
            if w != s:
                scores[w] += delta[w]
    # Undirected: each pair is counted from both endpoints.
    scale = 0.5
    if sources and len(sources) < n:
        scale *= n / len(sources)
    if normalized and n > 2:  # noqa: PLR2004 - normalization is undefined below 3 nodes
        scale *= 2.0 / ((n - 1) * (n - 2))
    return {v: score * scale for v, score in scores.items()}
