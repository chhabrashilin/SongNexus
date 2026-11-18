"""Taste profile ("Your Nexus"): what a set of artists says, computed from the graph alone.

Pure and deterministic; no model and no prose. Given a listener's artists and a
weight for each (play counts, or 1 each for an imported playlist), it reports:

- **Genre mix**: shares of top-level genres. Each artist's genre shares are
  summed per top-level genre and normalized, then weighted by the artist.
- **Decade spread**: shares of decades. Each artist contributes the decade
  distribution of the recordings they perform on (any credit when they perform
  on none), normalized, then weighted.
- **Most central artist**: the artist directly connected to the most of the
  listener's other artists.
- **Hidden connectors**: artists outside the list connected to two or more of
  its artists (the playlist analysis' connectors), most links first.
- **Tightest cluster**: the listener's k-core with the largest k: the biggest
  group in which every artist is directly connected to at least k others in the
  group.
- **Most surprising pair**: among the ``SURPRISE_POOL`` heaviest artists, the
  two connected by the longest shortest path (within ``MAX_STEPS``).
- **Collaborators reached**: distinct artists directly connected to any of them.

Weights use ``play_weight`` so a single much-played artist cannot drown out the rest.
"""

from __future__ import annotations

import heapq
import math
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from songnexus.core.browse import BrowseIndex
from songnexus.core.graph.playlist import hidden_links
from songnexus.core.model import PERFORMER_ROLES

MAX_ARTISTS = 500
MAX_GENRES = 10
MAX_CONNECTORS = 10
MAX_CLUSTER = 25
SURPRISE_POOL = 20
MAX_STEPS = 6
_PERFORMER_NAMES = tuple(sorted(r.value for r in PERFORMER_ROLES))


def play_weight(plays: int) -> float:
    """Weight of an artist played ``plays`` times: 1 + ln(plays), so 1 play weighs 1."""
    return 1.0 + math.log(max(plays, 1))


@dataclass(frozen=True)
class Slice:
    """A share of the listener's taste.

    Attributes:
        key: A genre ID or a decade (as a string, e.g. ``1990``).
        share: Share in [0, 1]; shares of one breakdown sum to 1.
        artist_count: The listener's artists that contribute to it.
    """

    key: str
    share: float
    artist_count: int


@dataclass(frozen=True)
class HiddenConnector:
    """An artist outside the list connected to several of the listener's artists."""

    artist_id: str
    linked: tuple[str, ...]


@dataclass(frozen=True)
class Cluster:
    """The tightest group: every member directly connects to ``min_links`` others in it."""

    artist_ids: tuple[str, ...]
    size: int
    min_links: int
    links: int


@dataclass(frozen=True)
class SurprisingPair:
    """Two of the listener's artists far apart in the graph."""

    a: str
    b: str
    steps: int


@dataclass(frozen=True)
class TasteProfile:
    """The result of ``profile``. Parts are None or empty when the data cannot support them.

    Attributes:
        artist_ids: The artists profiled, heaviest first.
        genres: Top-level genre shares, largest first (at most ``MAX_GENRES``).
        unknown_genre_artists: Profiled artists without genre data.
        decades: Decade shares, oldest first.
        undated_artists: Profiled artists without dated recordings.
        central: (artist, how many of the listener's artists it connects to directly).
        connectors: Hidden connectors, most links first.
        cluster: The tightest cluster.
        surprising_pair: The most surprising pair.
        collaborators_reached: Distinct artists connected to the profiled ones.
    """

    artist_ids: tuple[str, ...]
    genres: tuple[Slice, ...] = ()
    unknown_genre_artists: int = 0
    decades: tuple[Slice, ...] = ()
    undated_artists: int = 0
    central: tuple[str, int] | None = None
    connectors: tuple[HiddenConnector, ...] = ()
    cluster: Cluster | None = None
    surprising_pair: SurprisingPair | None = None
    collaborators_reached: int = 0


def _slices(totals: Mapping[str, float], counts: Counter[str]) -> list[Slice]:
    whole = sum(totals.values())
    if whole <= 0:
        return []
    return [Slice(k, v / whole, counts[k]) for k, v in totals.items()]


def _genre_mix(
    index: BrowseIndex, members: Sequence[str], weights: Mapping[str, float]
) -> tuple[list[Slice], int]:
    totals: dict[str, float] = defaultdict(float)
    counts: Counter[str] = Counter()
    unknown = 0
    for artist_id in members:
        per_root: dict[str, float] = defaultdict(float)
        for share in index.graph.nodes[artist_id].genres:
            for root in index.genre_roots.get(share.genre_id, ()):
                per_root[root] += share.share
        whole = sum(per_root.values())
        if whole <= 0:
            unknown += 1
            continue
        for root, value in per_root.items():
            totals[root] += weights[artist_id] * value / whole
            counts[root] += 1
    names = index.graph.genre_names
    ranked = sorted(_slices(totals, counts), key=lambda s: (-s.share, names[s.key], s.key))
    return ranked[:MAX_GENRES], unknown


def _decade_spread(
    index: BrowseIndex, members: Sequence[str], weights: Mapping[str, float]
) -> tuple[list[Slice], int]:
    totals: dict[str, float] = defaultdict(float)
    counts: Counter[str] = Counter()
    undated = 0
    for artist_id in members:
        decades = index.decades(artist_id, _PERFORMER_NAMES) or index.decades(artist_id)
        whole = sum(decades.values())
        if not whole:
            undated += 1
            continue
        for decade, n in decades.items():
            totals[str(decade)] += weights[artist_id] * n / whole
            counts[str(decade)] += 1
    return sorted(_slices(totals, counts), key=lambda s: s.key), undated


def _central(
    index: BrowseIndex, members: Sequence[str], links: Mapping[str, set[str]]
) -> tuple[str, int] | None:
    best = min(members, key=lambda a: (-len(links[a]), *index.connectedness_key(a)))
    return (best, len(links[best])) if links[best] else None


def _cluster(
    members: Sequence[str], links: Mapping[str, set[str]], weights: Mapping[str, float]
) -> Cluster | None:
    """The k-core with the largest k (Matula-Beck peeling), its biggest connected part."""
    degree = {a: len(links[a]) for a in members}
    heap = [(d, a) for a, d in degree.items()]
    heapq.heapify(heap)
    core: dict[str, int] = {}
    k = 0
    while heap:
        d, artist_id = heapq.heappop(heap)
        if artist_id in core or d != degree[artist_id]:
            continue  # stale entry
        k = max(k, d)
        core[artist_id] = k
        for other in links[artist_id]:
            if other not in core:
                degree[other] -= 1
                heapq.heappush(heap, (degree[other], other))
    top = max(core.values(), default=0)
    if top == 0:
        return None
    inner = {a for a, c in core.items() if c == top}
    parts: list[list[str]] = []
    seen: set[str] = set()
    for start in sorted(inner):
        if start in seen:
            continue
        part, queue = [], deque([start])
        seen.add(start)
        while queue:
            node = queue.popleft()
            part.append(node)
            for other in links[node]:
                if other in inner and other not in seen:
                    seen.add(other)
                    queue.append(other)
        parts.append(part)
    order = {a: i for i, a in enumerate(members)}
    # Biggest, then heaviest, then the one holding the listener's heaviest artist.
    best = max(
        parts,
        key=lambda p: (len(p), sum(weights[a] for a in p), -min(order[a] for a in p)),
    )
    best.sort(key=order.__getitem__)
    part_set = set(best)
    edges = sum(1 for a in best for b in links[a] if b in part_set) // 2
    return Cluster(tuple(best[:MAX_CLUSTER]), len(best), top, edges)


def _surprising_pair(
    index: BrowseIndex, pool: Sequence[str], allowed: Callable[[str], bool] | None
) -> SurprisingPair | None:
    """BFS from each pool artist (bounded depth); the farthest connected pair wins."""
    adjacency = index.adjacency
    targets = set(pool)
    best: tuple[int, int, int] | None = None  # (steps, -i, -j) maximized
    for i, source in enumerate(pool):
        remaining = set(pool[i + 1 :])
        distances = {source: 0}
        queue = deque([source])
        while queue and remaining:
            node = queue.popleft()
            depth = distances[node]
            if depth >= MAX_STEPS:
                break
            for other in adjacency[node]:
                if other in distances:
                    continue
                if other not in targets and allowed is not None and not allowed(other):
                    continue
                distances[other] = depth + 1
                remaining.discard(other)
                queue.append(other)
        for j in range(i + 1, len(pool)):
            steps = distances.get(pool[j])
            if steps is not None and (best is None or (steps, -i, -j) > best):
                best = (steps, -i, -j)
    if best is None or best[0] < 2:  # noqa: PLR2004 - direct neighbors are no surprise
        return None
    return SurprisingPair(pool[-best[1]], pool[-best[2]], best[0])


def profile(
    index: BrowseIndex,
    weights: Mapping[str, float],
    *,
    allowed: Callable[[str], bool] | None = None,
) -> TasteProfile:
    """Profiles a listener's artists.

    Args:
        index: The browse index.
        weights: Artist -> weight (see ``play_weight``), in the caller's order of
            importance (it breaks ties); unknown artists are ignored.
        allowed: Which artists may appear as connectors, cluster members or path
            steps (the viewer's blocks).
    """
    graph = index.graph
    # Heaviest first; equal weights keep the caller's order (the sort is stable).
    members = sorted(
        (a for a in weights if a in graph.nodes and (allowed is None or allowed(a))),
        key=lambda a: -weights[a],
    )[:MAX_ARTISTS]
    if not members:
        return TasteProfile(())
    member_set = set(members)
    adjacency = index.adjacency
    links = {a: {b for b in adjacency[a] if b in member_set} for a in members}
    genres, unknown = _genre_mix(index, members, weights)
    decades, undated = _decade_spread(index, members, weights)
    connectors = hidden_links(
        adjacency,
        members,
        {a: graph.nodes[a].name for a in members},
        allowed=allowed,
        not_connectors=graph.other_identities(members),
    )
    connectors.sort(key=lambda c: (-len(c.linked), -c.score, graph.nodes[c.artist_id].name))
    reached = {
        b
        for a in members
        for b in adjacency[a]
        if b not in member_set and (allowed is None or allowed(b))
    }
    return TasteProfile(
        artist_ids=tuple(members),
        genres=tuple(genres),
        unknown_genre_artists=unknown,
        decades=tuple(decades),
        undated_artists=undated,
        central=_central(index, members, links),
        connectors=tuple(
            HiddenConnector(c.artist_id, c.linked) for c in connectors[:MAX_CONNECTORS]
        ),
        cluster=_cluster(members, links, weights),
        surprising_pair=_surprising_pair(index, members[:SURPRISE_POOL], allowed),
        collaborators_reached=len(reached),
    )
