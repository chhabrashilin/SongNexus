"""Listener overlap: the privacy floor and strength from ranks."""

from songnexus.core.listening import MIN_LISTENERS, Audience, Strength, overlap, strength_of

BIG = Audience(listeners=10_000, listens=500_000)


def test_strength_comes_from_the_better_rank() -> None:
    assert strength_of(1) is Strength.STRONG
    assert strength_of(10) is Strength.STRONG
    assert strength_of(11) is Strength.MODERATE
    assert strength_of(51) is Strength.WEAK
    assert strength_of(None) is Strength.NONE
    result = overlap(BIG, BIG, rank_b_for_a=80, rank_a_for_b=4)
    assert result is not None
    assert result.strength is Strength.STRONG


def test_small_audiences_are_not_described() -> None:
    small = Audience(listeners=MIN_LISTENERS - 1, listens=900)
    assert overlap(BIG, small, 1, 1) is None
    assert overlap(BIG, None, 1, 1) is None
    edge = overlap(BIG, Audience(listeners=MIN_LISTENERS, listens=60), None, None)
    assert edge is not None
    assert edge.strength is Strength.NONE
