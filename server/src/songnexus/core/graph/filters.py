"""Node filters: genre selection (US-12) and artist blocks (US-17).

A filter becomes a node predicate that graph algorithms apply inside the search,
so a filtered-out artist is never part of a result, including as an
intermediate step of a path.
"""

from __future__ import annotations

from dataclasses import dataclass

from songnexus.core.graph.algorithms import NodePredicate
from songnexus.core.graph.model import ArtistGraph, ArtistNode

DEFAULT_MIN_GENRE_SHARE = 0.20


@dataclass(frozen=True)
class NodeFilter:
    """Which artists may appear in a result.

    Attributes:
        genre_ids: When non-empty, an artist with genre data must have at least
            ``min_genre_share`` of its genre votes in one of these genres.
        min_genre_share: The share threshold (tunable, plan US-12).
        include_unknown_genre: Whether artists with no genre data pass a genre
            filter. They often are the producers and session players who bridge
            scenes, so the default is to keep them.
        blocked: Artists the viewer blocked. They never pass.
    """

    genre_ids: frozenset[str] = frozenset()
    min_genre_share: float = DEFAULT_MIN_GENRE_SHARE
    include_unknown_genre: bool = True
    blocked: frozenset[str] = frozenset()

    @property
    def is_empty(self) -> bool:
        """True when the filter lets every artist through."""
        return not self.genre_ids and not self.blocked

    def allows(self, node: ArtistNode) -> bool:
        """Returns whether ``node`` passes this filter."""
        if node.id in self.blocked:
            return False
        if not self.genre_ids:
            return True
        if not node.genres:
            return self.include_unknown_genre
        return any(
            g.genre_id in self.genre_ids and g.share >= self.min_genre_share for g in node.genres
        )

    def predicate(self, graph: ArtistGraph) -> NodePredicate | None:
        """Returns a node predicate over ``graph``, or None when nothing is filtered."""
        if self.is_empty:
            return None
        nodes = graph.nodes
        return lambda node_id: node_id in nodes and self.allows(nodes[node_id])


def genre_coverage(graph: ArtistGraph, artist_ids: list[str]) -> float:
    """Returns the share of ``artist_ids`` with genre data (shown next to genre filters)."""
    if not artist_ids:
        return 0.0
    known = sum(1 for a in artist_ids if a in graph.nodes and graph.nodes[a].genres)
    return known / len(artist_ids)
