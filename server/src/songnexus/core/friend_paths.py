"""Friend paths: how two friends' top artists connect (roadmap growth loop 4). Pure.

Given each friend's top artists, returns what they share outright, the
collaborators both sides' artists worked with, and a handful of the shortest
connection paths between one side's artists and the other's. Who may see whose
top artists is decided by the caller (both must opt in; blocks and the
viewer's artist blocklist apply), never here.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from songnexus.core.graph.algorithms import NodePredicate, bidirectional_bfs_path

TOP_ARTISTS = 5
MAX_PATHS = 5
MAX_SHARED_COLLABORATORS = 8
MAX_PATH_STEPS = 6
# Each of a person's artists starts at most this many of the returned paths, so a
# well-connected artist doesn't take every slot.
PATHS_PER_ARTIST = 2

Adjacency = Mapping[str, Mapping[str, float]]


def top_artists(
    chosen: Sequence[str],
    tallies: Iterable[tuple[str, int]],
    *,
    known: Callable[[str], bool],
    hidden: frozenset[str],
    limit: int = TOP_ARTISTS,
) -> list[str]:
    """Returns a person's top artists: their chosen Top 5 first, then their most played.

    Artists outside the catalog or in ``hidden`` are skipped.
    """
    plays: Counter[str] = Counter()
    for artist_id, count in tallies:
        plays[artist_id] += count
    ordered = [*chosen, *(a for a, _ in sorted(plays.items(), key=lambda p: (-p[1], p[0])))]
    result: list[str] = []
    for artist_id in ordered:
        if artist_id not in result and artist_id not in hidden and known(artist_id):
            result.append(artist_id)
        if len(result) == limit:
            break
    return result


@dataclass(frozen=True)
class SharedCollaborator:
    """An artist connected directly to at least one artist on each side."""

    artist_id: str
    mine: tuple[str, ...]
    theirs: tuple[str, ...]


@dataclass(frozen=True)
class FriendConnections:
    """What connects two people's top artists."""

    shared: tuple[str, ...]
    collaborators: tuple[SharedCollaborator, ...]
    paths: tuple[tuple[str, ...], ...]


def connect(
    adjacency: Adjacency,
    mine: Sequence[str],
    theirs: Sequence[str],
    *,
    allowed: NodePredicate | None = None,
    max_steps: int = MAX_PATH_STEPS,
) -> FriendConnections:
    """Finds shared artists, shared collaborators and the shortest cross paths.

    Paths run from one of ``mine`` to one of ``theirs`` (artists both have are
    reported as shared, not as paths). Shorter first, then by how high both
    artists are in their lists; intermediate artists must satisfy ``allowed``.
    """
    shared = tuple(a for a in mine if a in set(theirs))
    mine_only = [a for a in mine if a not in shared]
    theirs_only = [b for b in theirs if b not in shared]

    candidates: list[tuple[int, int, tuple[str, ...]]] = []
    for i, a in enumerate(mine_only):
        for j, b in enumerate(theirs_only):
            path = bidirectional_bfs_path(
                adjacency, a, b, max_depth=max_steps, allowed=allowed
            ).path
            if path is not None:
                candidates.append((len(path), i + j, path))
    candidates.sort()
    starts: Counter[str] = Counter()
    ends: Counter[str] = Counter()
    paths: list[tuple[str, ...]] = []
    for _, _, path in candidates:
        if starts[path[0]] >= PATHS_PER_ARTIST or ends[path[-1]] >= PATHS_PER_ARTIST:
            continue
        starts[path[0]] += 1
        ends[path[-1]] += 1
        paths.append(path)
        if len(paths) == MAX_PATHS:
            break

    sides = set(mine) | set(theirs)
    by_mine: dict[str, set[str]] = defaultdict(set)
    by_theirs: dict[str, set[str]] = defaultdict(set)
    for a in mine:
        for n in adjacency.get(a, {}):
            by_mine[n].add(a)
    for b in theirs:
        for n in adjacency.get(b, {}):
            by_theirs[n].add(b)
    common = [
        n
        for n in by_mine.keys() & by_theirs.keys()
        if n not in sides and (allowed is None or allowed(n))
    ]
    common.sort(key=lambda n: (-(len(by_mine[n]) + len(by_theirs[n])), n))
    collaborators = tuple(
        SharedCollaborator(
            n,
            tuple(a for a in mine if a in by_mine[n]),
            tuple(b for b in theirs if b in by_theirs[n]),
        )
        for n in common[:MAX_SHARED_COLLABORATORS]
    )
    return FriendConnections(shared, collaborators, tuple(paths))
