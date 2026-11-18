"""Re-ranking: turn a scored list into a feed that stays varied and keeps learning.

Greedy, one slot at a time:

- **Relevance vs. redundancy** (maximal marginal relevance, Carbonell and
  Goldstein 1998): each slot takes the candidate maximizing
  ``λ·value − (1 − λ)·max similarity to the last few placed``, so near
  duplicates of what is already on screen wait.
- **Genre spacing**: at most ``genre_max`` cards of one top-level genre in any
  window of ``genre_window`` consecutive cards.
- **Exploration**: every ``explore_every``-th slot goes to the best candidate
  the listener has never been shown (or an ``EXPLORE`` candidate), chosen by
  Thompson-style sampling around its value, so the feed does not collapse
  onto what it already knows works.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RerankConfig:
    """Re-ranking settings (an experiment arm can change them)."""

    mmr_lambda: float = 0.75
    similarity_window: int = 6
    genre_window: int = 5
    genre_max: int = 2
    explore_every: int = 7
    explore_noise: float = 0.15
    length: int = 100


@dataclass(frozen=True)
class Scored:
    """A candidate with its ranking value."""

    artist_id: str
    value: float
    exploratory: bool  # never shown before, or proposed by the EXPLORE source
    genre: str | None


def rerank(
    items: Sequence[Scored],
    similarity: Callable[[str, str], float],
    rng: random.Random,
    config: RerankConfig | None = None,
) -> list[Scored]:
    """The feed order (at most ``config.length`` items)."""
    config = config or RerankConfig()
    pool = sorted(items, key=lambda s: (-s.value, s.artist_id))
    if not pool:
        return []
    top, bottom = pool[0].value, pool[-1].value
    span = (top - bottom) or 1.0
    norm: Mapping[str, float] = {s.artist_id: (s.value - bottom) / span for s in pool}
    placed: list[Scored] = []
    remaining = list(pool)

    def genre_ok(candidate: Scored) -> bool:
        if candidate.genre is None:
            return True
        window = placed[-(config.genre_window - 1) :] if config.genre_window > 1 else []
        return sum(1 for p in window if p.genre == candidate.genre) < config.genre_max

    def redundancy(candidate: Scored) -> float:
        recent = placed[-config.similarity_window :]
        return max((similarity(candidate.artist_id, p.artist_id) for p in recent), default=0.0)

    while remaining and len(placed) < config.length:
        slot = len(placed) + 1
        allowed = [c for c in remaining if genre_ok(c)] or remaining
        exploring = config.explore_every and slot % config.explore_every == 0
        explorers = [c for c in allowed if c.exploratory] if exploring else []
        if explorers:
            # Sample around each value: uncertain items get a fair chance.
            choice = max(
                explorers[:30],
                key=lambda c: norm[c.artist_id] + rng.gauss(0.0, config.explore_noise),
            )
        else:
            choice = max(
                allowed[:80],
                key=lambda c: (
                    config.mmr_lambda * norm[c.artist_id] - (1 - config.mmr_lambda) * redundancy(c),
                    c.artist_id,
                ),
            )
        placed.append(choice)
        remaining.remove(choice)
    return placed
