"""Listener overlap (R2-5, S2): how much two artists share an audience, from aggregate data.

Inputs are public aggregates (ListenBrainz): each artist's listener count, and
each artist's ranked list of the artists most often played in the same
listening sessions (top 100). Nothing here touches an individual listener.

* Overlap is shown only when both artists have at least ``MIN_LISTENERS``
  listeners (a k-anonymity floor: small audiences are not described), always
  with the counts it rests on.
* **Strength** comes from the best rank either artist holds in the other's
  co-listening list: STRONG in the top 10, MODERATE in the top 50, WEAK in the
  top 100, NONE when in neither list. Ranks, not raw scores, because scores are
  not comparable across artists with different audience sizes.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

MIN_LISTENERS = 50
STRONG_RANK = 10
MODERATE_RANK = 50


class Strength(enum.StrEnum):
    """How strongly two audiences overlap."""

    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NONE = "NONE"


@dataclass(frozen=True)
class Audience:
    """An artist's aggregate audience."""

    listeners: int
    listens: int


@dataclass(frozen=True)
class Overlap:
    """Listener overlap between two artists.

    Attributes:
        audience_a: A's listeners and listens.
        audience_b: B's listeners and listens.
        rank_b_for_a: B's rank among the artists A's listeners also play (1 = most), or None.
        rank_a_for_b: A's rank among the artists B's listeners also play, or None.
        strength: Derived from the better of the two ranks.
    """

    audience_a: Audience
    audience_b: Audience
    rank_b_for_a: int | None
    rank_a_for_b: int | None
    strength: Strength


def strength_of(best_rank: int | None) -> Strength:
    """Maps the better rank to a strength."""
    if best_rank is None:
        return Strength.NONE
    if best_rank <= STRONG_RANK:
        return Strength.STRONG
    if best_rank <= MODERATE_RANK:
        return Strength.MODERATE
    return Strength.WEAK


def overlap(
    audience_a: Audience | None,
    audience_b: Audience | None,
    rank_b_for_a: int | None,
    rank_a_for_b: int | None,
) -> Overlap | None:
    """Returns the overlap, or None when either audience is unknown or below the floor."""
    if audience_a is None or audience_b is None:
        return None
    if min(audience_a.listeners, audience_b.listeners) < MIN_LISTENERS:
        return None
    ranks = [r for r in (rank_b_for_a, rank_a_for_b) if r is not None]
    return Overlap(
        audience_a,
        audience_b,
        rank_b_for_a,
        rank_a_for_b,
        strength_of(min(ranks) if ranks else None),
    )
