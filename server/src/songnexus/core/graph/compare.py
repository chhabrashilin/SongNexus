"""Two-artist comparison (US-05): shared genres, mutual collaborators, the path between."""

from __future__ import annotations

from dataclasses import dataclass

from songnexus.core.graph.algorithms import PathResult, bidirectional_bfs_path
from songnexus.core.graph.collaborations import CollaborationType, collaboration_counts
from songnexus.core.graph.filters import NodeFilter
from songnexus.core.graph.model import ArtistGraph, EdgeKind, GenreShare


@dataclass(frozen=True)
class SharedGenre:
    """A genre both artists carry, with each one's share."""

    genre_id: str
    name: str
    share_a: float
    share_b: float


@dataclass(frozen=True)
class Comparison:
    """Everything the compare screen shows.

    Attributes:
        artist_a: The first artist.
        artist_b: The second artist.
        genre_overlap: Weighted genre overlap in [0, 1]: the sum over genres of
            the smaller of the two shares. None when either has no genre data.
        shared_genres: Genres both carry, by combined share.
        mutual_collaborators: Exactly the intersection of the two artists' direct
            connections under the enabled kinds (AC-5.1), by name.
        directly_connected: Whether the two are themselves connected.
        path: The fewest-steps path between them.
        counts_a: ``artist_a``'s collaborator counts by type.
        counts_b: ``artist_b``'s collaborator counts by type.
    """

    artist_a: str
    artist_b: str
    genre_overlap: float | None
    shared_genres: tuple[SharedGenre, ...]
    mutual_collaborators: tuple[str, ...]
    directly_connected: bool
    path: PathResult
    counts_a: dict[CollaborationType, int]
    counts_b: dict[CollaborationType, int]


def _shared_genres(a: tuple[GenreShare, ...], b: tuple[GenreShare, ...]) -> list[SharedGenre]:
    shares_b = {g.genre_id: g for g in b}
    shared = [
        SharedGenre(g.genre_id, g.name, g.share, shares_b[g.genre_id].share)
        for g in a
        if g.genre_id in shares_b
    ]
    shared.sort(key=lambda s: (-(s.share_a + s.share_b), s.name))
    return shared


def compare(
    graph: ArtistGraph,
    artist_a: str,
    artist_b: str,
    kinds: frozenset[EdgeKind],
    *,
    node_filter: NodeFilter | None = None,
    max_depth: int = 6,
) -> Comparison:
    """Compares two artists.

    Raises:
        KeyError: Either artist is not in the graph.
    """
    node_a, node_b = graph.nodes[artist_a], graph.nodes[artist_b]
    shared = _shared_genres(node_a.genres, node_b.genres)
    overlap = (
        sum(min(s.share_a, s.share_b) for s in shared) if node_a.genres and node_b.genres else None
    )

    adjacency = graph.adjacency(kinds)
    allowed = node_filter.predicate(graph) if node_filter else None
    neighbors_a, neighbors_b = set(adjacency[artist_a]), set(adjacency[artist_b])
    mutual = {n for n in neighbors_a & neighbors_b if allowed is None or allowed(n)}

    return Comparison(
        artist_a=artist_a,
        artist_b=artist_b,
        genre_overlap=overlap,
        shared_genres=tuple(shared),
        mutual_collaborators=tuple(sorted(mutual, key=lambda n: (graph.nodes[n].name, n))),
        directly_connected=artist_b in neighbors_a,
        path=bidirectional_bfs_path(
            adjacency, artist_a, artist_b, max_depth=max_depth, allowed=allowed
        ),
        counts_a=collaboration_counts(graph, artist_a, node_filter),
        counts_b=collaboration_counts(graph, artist_b, node_filter),
    )
