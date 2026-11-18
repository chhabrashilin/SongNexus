"""The daily connection puzzle (US-04): rules, fairness and hints. Pure and deterministic.

Rules: get from the start artist to the target by naming artists who are
directly connected, one step at a time; every accepted step shows the credit
that connects them.

- Same puzzle for everyone each day; shuffled cycles do not repeat an unordered
  pair until the cycle is exhausted (for a fixed catalog, no puzzle storage).
- Fair: start and target are well-known artists (fully looked up seeds) whose
  shortest connection is 3 or 4 steps, so it is never trivial and always solvable.
- After a correct step the player learns how many steps remain (warmer/colder);
  a wrong step reveals nothing.
- Hints: three of the current artist's connections, at least one of them
  closer to the target, the same for every player.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from songnexus.core.graph.algorithms import NodePredicate, bfs_distances

LAUNCH_DAY = date(2026, 10, 7)  # puzzle #1
MIN_PAR = 3
MAX_PAR = 4
HINT_SIZE = 3
SCHEDULE_SEED = "songnexus-daily-v2"
# Beyond this, "steps left" stops being useful feedback; report "no route from here".
MAX_REMAINING = 8


@dataclass(frozen=True)
class Puzzle:
    """One day's puzzle."""

    day: date
    number: int
    start: str
    target: str
    par: int


def _stable_int(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)


def candidate_pairs(
    adjacency: Mapping[str, Mapping[str, float]], pool: list[str]
) -> list[tuple[str, str, int]]:
    """Returns every (a, b, par) with a < b from the pool at distance MIN_PAR..MAX_PAR.

    Deterministic: the pool is sorted, so the list (and so each day's pick) is a
    function of the catalog alone.
    """
    members = sorted(p for p in set(pool) if p in adjacency)
    pairs: list[tuple[str, str, int]] = []
    for i, a in enumerate(members):
        distances = bfs_distances(adjacency, a, max_depth=MAX_PAR)
        for b in members[i + 1 :]:
            d = distances.get(b)
            if d is not None and MIN_PAR <= d <= MAX_PAR:
                pairs.append((a, b, d))
    return pairs


@lru_cache(maxsize=16)
def _schedule(
    pairs: tuple[tuple[str, str, int], ...], cycle: int
) -> tuple[tuple[str, str, int], ...]:
    deck = list(pairs)
    random.Random(_stable_int(f"{SCHEDULE_SEED}:{cycle}")).shuffle(deck)  # noqa: S311
    return tuple(deck)


def puzzle_for(day: date, pairs: list[tuple[str, str, int]]) -> Puzzle:
    """Returns the day's puzzle without repeating a pair within the current cycle.

    Raises:
        ValueError: There are no candidate pairs, or the day precedes launch.
    """
    if not pairs:
        raise ValueError("no fair puzzle pairs in this catalog")
    if day < LAUNCH_DAY:
        raise ValueError("the first puzzle is on the launch day")
    cycle, position = divmod((day - LAUNCH_DAY).days, len(pairs))
    a, b, par = _schedule(tuple(pairs), cycle)[position]
    if _stable_int(day.isoformat()) & 1:  # vary which end is the start
        a, b = b, a
    return Puzzle(day, (day - LAUNCH_DAY).days + 1, a, b, par)


def steps_to_target(
    adjacency: Mapping[str, Mapping[str, float]], artist: str, target: str
) -> int | None:
    """Returns the steps left from ``artist`` to the target, or None beyond MAX_REMAINING."""
    return bfs_distances(adjacency, target, max_depth=MAX_REMAINING).get(artist)


def hint(
    adjacency: Mapping[str, Mapping[str, float]],
    current: str,
    target: str,
    *,
    allowed: NodePredicate | None = None,
) -> list[str]:
    """Returns up to HINT_SIZE connections of ``current``, at least one closest to the target.

    The same for everyone at the same position (seeded by position, not player).
    Artists the player blocked are never suggested when ``allowed`` says so.
    Returns no options if solved or no eligible neighbor gets closer.
    """
    neighbors = sorted(n for n in adjacency.get(current, {}) if allowed is None or allowed(n))
    if not neighbors:
        return []
    to_target = bfs_distances(adjacency, target)
    reachable = [n for n in neighbors if n in to_target]
    if not reachable or current == target:
        return []
    best = min(to_target[n] for n in reachable)
    if best >= to_target.get(current, best):
        return []
    closest = [n for n in reachable if to_target[n] == best]
    rng = random.Random(_stable_int(f"{current}|{target}"))  # noqa: S311 - not security
    chosen = [rng.choice(closest)]
    others = [n for n in neighbors if n != chosen[0]]
    chosen += rng.sample(others, min(HINT_SIZE - 1, len(others)))
    rng.shuffle(chosen)
    return chosen
