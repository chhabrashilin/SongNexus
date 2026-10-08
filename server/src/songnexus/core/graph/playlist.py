"""Playlist analysis (US-10): how a playlist's artists connect.

- Cohesion: the share of artist pairs within 2 steps of each other.
- Connectors: artists outside the playlist linked to at least two of its
  artists ("hidden links"), scored by summed connection strength.
- The thread: shortest paths between consecutive playlist artists, joined.
- Links: direct connections between playlist artists.

Pairs within 2 steps are found by enumerating, for every artist x, the
playlist artists adjacent to x: all of them are within 2 steps of each other
through x. That costs the sum over x of (playlist neighbors of x)², far less
than a search per pair. Filtered artists (blocks, genres) never serve as the
intermediate x or appear on the thread (plan §16.4).
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from songnexus.core.graph.algorithms import NodePredicate, bidirectional_bfs_path

THREAD_MAX_ARTISTS = 25
THREAD_MAX_STEPS = 4
MAX_CONNECTORS = 10
MAX_LINKS = 100


@dataclass(frozen=True)
class Connector:
    """An artist outside the playlist that links several of its artists."""

    artist_id: str
    linked: tuple[str, ...]
    score: float


@dataclass(frozen=True)
class PlaylistAnalysis:
    """The result of ``analyze_playlist``.

    Attributes:
        pairs: Number of artist pairs considered.
        pairs_within_two: Pairs at most 2 steps apart.
        connectors: Strongest connectors first.
        thread: Artist IDs along the joined paths, starting at the first artist.
        thread_breaks: Consecutive artists with no path within the step limit.
        links: Direct connections between playlist artists, strongest first.
    """

    pairs: int
    pairs_within_two: int
    connectors: tuple[Connector, ...]
    thread: tuple[str, ...]
    thread_breaks: int
    links: tuple[tuple[str, str, float], ...]

    @property
    def cohesion(self) -> float | None:
        """Share of pairs within 2 steps, or None with fewer than two artists."""
        return self.pairs_within_two / self.pairs if self.pairs else None


def _direct_links(
    adjacency: Mapping[str, Mapping[str, float]], members: Sequence[str], member_set: set[str]
) -> list[tuple[str, str, float]]:
    links = [
        (a, b, strength)
        for a in members
        for b, strength in adjacency[a].items()
        if b in member_set and a < b
    ]
    links.sort(key=lambda link: (-link[2], link[0], link[1]))
    return links


def _pairs_via_intermediates(
    adjacency: Mapping[str, Mapping[str, float]],
    members: Sequence[str],
    member_set: set[str],
    *,
    names: Mapping[str, str],
    allowed: NodePredicate | None,
    not_connectors: frozenset[str],
) -> tuple[set[tuple[str, str]], list[Connector]]:
    """Returns pairs linked through some allowed artist, and the connectors."""
    touching: dict[str, list[str]] = defaultdict(list)
    for member in members:
        for x in adjacency[member]:
            touching[x].append(member)
    pairs: set[tuple[str, str]] = set()
    connectors: list[Connector] = []
    for x, linked in touching.items():
        if len(linked) < 2 or (allowed is not None and not allowed(x)):  # noqa: PLR2004
            continue
        ordered = sorted(linked)
        pairs.update(itertools.combinations(ordered, 2))
        if x not in member_set and x not in not_connectors:
            score = sum(adjacency[x][m] for m in linked)
            by_name = tuple(sorted(linked, key=lambda m: names.get(m, m)))
            connectors.append(Connector(x, by_name, score))
    connectors.sort(key=lambda c: (-c.score, names.get(c.artist_id, ""), c.artist_id))
    return pairs, connectors


def _thread(
    adjacency: Mapping[str, Mapping[str, float]],
    members: Sequence[str],
    allowed: NodePredicate | None,
) -> tuple[list[str], int]:
    """Joins shortest paths between consecutive members; returns (thread, breaks)."""
    thread: list[str] = list(members[:1])
    breaks = 0
    for a, b in itertools.pairwise(members[:THREAD_MAX_ARTISTS]):
        result = bidirectional_bfs_path(
            adjacency, a, b, max_depth=THREAD_MAX_STEPS, allowed=allowed, max_expansions=5_000
        )
        if result.path is None:
            breaks += 1
            thread.append(b)
        else:
            thread.extend(result.path[1:])
    return thread, breaks


def analyze_playlist(
    adjacency: Mapping[str, Mapping[str, float]],
    artist_ids: Sequence[str],
    names: Mapping[str, str],
    *,
    allowed: NodePredicate | None = None,
    not_connectors: frozenset[str] = frozenset(),
) -> PlaylistAnalysis:
    """Analyzes a playlist's matched artists, in playlist order.

    Args:
        adjacency: The graph under the enabled connection kinds.
        artist_ids: Matched artists in order of first appearance.
        names: Display names, for deterministic tie-breaks.
        allowed: Which artists may be intermediates (blocks, genre filters).
        not_connectors: Artists never reported as hidden links, such as another
            identity of a playlist artist (a legal name, a persona).
    """
    members = [a for a in dict.fromkeys(artist_ids) if a in adjacency]
    member_set = set(members)
    links = _direct_links(adjacency, members, member_set)
    pairs, connectors = _pairs_via_intermediates(
        adjacency,
        members,
        member_set,
        names=names,
        allowed=allowed,
        not_connectors=not_connectors,
    )
    pairs.update((a, b) for a, b, _ in links)
    thread, breaks = _thread(adjacency, members, allowed)
    n = len(members)
    return PlaylistAnalysis(
        pairs=n * (n - 1) // 2,
        pairs_within_two=len(pairs),
        connectors=tuple(connectors[:MAX_CONNECTORS]),
        thread=tuple(thread),
        thread_breaks=breaks,
        links=tuple(links[:MAX_LINKS]),
    )
