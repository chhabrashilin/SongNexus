"""The catalog as Z-star reads it: one lean view built per catalog version.

Built once from the browse index and shared read-only across requests, like
the index itself. Everything here is derived; nothing is personal.
"""

from __future__ import annotations

import bisect
import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import accumulate

from songnexus.core.browse import BrowseIndex

GENRE_POOL = 120  # most popular artists kept per top-level genre


@dataclass(frozen=True)
class WalkNeighbors:
    """An artist's neighbors with cumulative weights, for weighted random steps."""

    ids: tuple[str, ...]
    cumulative: tuple[float, ...]

    def pick(self, u: float) -> str:
        """The neighbor at position ``u`` in [0, 1) of the weight mass."""
        return self.ids[bisect.bisect_right(self.cumulative, u * self.cumulative[-1])]


@dataclass(frozen=True)
class Catalog:
    """What retrieval and ranking need to know about artists.

    Attributes:
        version: Catalog version.
        names: Artist -> display name.
        performers: Artists with something to play (only these are recommended).
        popularity: Artist -> [0, 1], log listeners (or connection strength when
            listener data is missing), relative to the most popular artist.
        has_image: Artists with a photo.
        genres: Artist -> top-level genre -> share.
        primary_genre: Artist -> its main top-level genre.
        genre_names: Genre ID -> name.
        genre_pool: Top-level genre -> its most popular performers, most popular first.
        colistening: Artist -> {other: rank}, both directions merged (best rank kept).
        adjacency: Collaboration strength between artists.
        walk: Artist -> neighbors for random walks (credits and co-listening).
    """

    version: str
    names: Mapping[str, str]
    performers: frozenset[str]
    popularity: Mapping[str, float]
    has_image: frozenset[str]
    genres: Mapping[str, Mapping[str, float]]
    primary_genre: Mapping[str, str]
    genre_names: Mapping[str, str]
    genre_pool: Mapping[str, tuple[str, ...]]
    colistening: Mapping[str, Mapping[str, int]]
    adjacency: Mapping[str, Mapping[str, float]]
    walk: Mapping[str, WalkNeighbors] = field(default_factory=dict)

    @property
    def popular(self) -> tuple[str, ...]:
        """Performers, most popular first (ties by ID)."""
        return tuple(sorted(self.performers, key=lambda a: (-self.popularity.get(a, 0.0), a)))


def _walk_neighbors(
    adjacency: Mapping[str, Mapping[str, float]],
    colistening: Mapping[str, Mapping[str, int]],
) -> dict[str, WalkNeighbors]:
    weights: dict[str, dict[str, float]] = defaultdict(dict)
    for u, nbrs in adjacency.items():
        for v, w in nbrs.items():
            weights[u][v] = weights[u].get(v, 0.0) + math.log1p(w)
    for u, ranked in colistening.items():
        for v, rank in ranked.items():
            weights[u][v] = weights[u].get(v, 0.0) + 1.0 / math.sqrt(rank)
    out = {}
    for u, nbrs in weights.items():
        ordered = sorted(nbrs.items())
        if ordered:
            out[u] = WalkNeighbors(
                ids=tuple(v for v, _ in ordered),
                cumulative=tuple(accumulate(w for _, w in ordered)),
            )
    return out


def build_catalog(index: BrowseIndex) -> Catalog:
    """Derives the Z-star view from a browse index."""
    graph = index.graph
    listeners = index.listeners
    max_listeners = max(listeners.values(), default=0)
    max_strength = max(index.strength.values(), default=0.0)

    def popularity(artist_id: str) -> float:
        heard = listeners.get(artist_id, 0)
        if heard and max_listeners:
            return math.log1p(heard) / math.log1p(max_listeners)
        strength = index.strength.get(artist_id, 0.0)
        # Without listener data, connection strength stands in, capped lower.
        return 0.5 * math.log1p(strength) / math.log1p(max_strength) if max_strength else 0.0

    genres: dict[str, dict[str, float]] = {}
    for node in graph.nodes.values():
        roots: dict[str, float] = defaultdict(float)
        for share in node.genres:
            for root in index.genre_roots.get(share.genre_id, ()):
                roots[root] += share.share
        total = sum(roots.values())
        if total:
            genres[node.id] = {g: s / total for g, s in roots.items()}

    pop = {a: popularity(a) for a in graph.nodes}
    pools: dict[str, list[str]] = defaultdict(list)
    for artist_id in sorted(index.performers, key=lambda a: (-pop.get(a, 0.0), a)):
        main = index.primary_root.get(artist_id)
        if main is not None and len(pools[main]) < GENRE_POOL:
            pools[main].append(artist_id)

    colistening: dict[str, dict[str, int]] = defaultdict(dict)
    for u, ranked in index.colistening.items():
        for v, rank in ranked.items():
            for a, b in ((u, v), (v, u)):
                if rank < colistening[a].get(b, 10**9):
                    colistening[a][b] = rank

    adjacency = {a: dict(n) for a, n in index.adjacency.items()}
    return Catalog(
        version=graph.version,
        names={a: n.name for a, n in graph.nodes.items()},
        performers=frozenset(index.performers),
        popularity=pop,
        has_image=frozenset(graph.images),
        genres=genres,
        primary_genre=dict(index.primary_root),
        genre_names=dict(graph.genre_names),
        genre_pool={g: tuple(a) for g, a in pools.items()},
        colistening=dict(colistening),
        adjacency=adjacency,
        walk=_walk_neighbors(adjacency, colistening),
    )
