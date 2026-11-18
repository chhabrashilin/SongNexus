from __future__ import annotations

from dataclasses import dataclass

import pytest

from songnexus.core.graph.relevance import (
    best_songs_first,
    is_variant_title,
    relevance,
)


@pytest.mark.parametrize(
    "title",
    [
        "Average Joe (3 Beat Blend)",
        "HUMBLE. (Skrillex Remix)",
        "Alright - Live at the Grammys",
        "King Kunta [Instrumental]",
        "Money Trees (Radio Edit)",
        "Bitch, Don't Kill My Vibe (Remix)",
        "Swimming Pools (Drank) - Extended Version",
        "Song (2015 Remastered)",
    ],
)
def test_variants_are_recognized(title: str) -> None:
    assert is_variant_title(title)


@pytest.mark.parametrize(
    "title",
    [
        "All the Stars",
        "Swimming Pools (Drank)",
        "Money Trees",
        "LOVE.",
        "Mixed Feelings",  # "mix" only counts as a word inside brackets or after a dash
        "Live Forever",
        "Demons (feat. Jay Rock)",
        None,
        "",
    ],
)
def test_originals_are_not_variants(title: str | None) -> None:
    assert not is_variant_title(title)


def test_reach_lifts_a_famous_artist_over_a_slightly_stronger_unknown() -> None:
    famous = relevance(strength=3, listeners=150_000)
    unknown_producer = relevance(strength=15, listeners=None)
    assert famous > unknown_producer


def test_strength_still_wins_by_a_wide_margin() -> None:
    frequent_producer = relevance(strength=50, listeners=1_500)
    one_off_feature = relevance(strength=1, listeners=20_000)
    assert frequent_producer > one_off_feature


def test_relevance_handles_missing_and_zero() -> None:
    assert relevance(0, None) == 0
    assert relevance(0, 0) == 0
    assert relevance(-1, None) == 0  # never negative
    assert relevance(1, None) == pytest.approx(1.0)


@dataclass(frozen=True)
class Item:
    subject_title: str | None
    order: int


def test_best_songs_first_is_stable_and_moves_variants_back() -> None:
    items = [
        Item("2Nite", 0),
        Item("Average Joe (3 Beat Blend)", 1),
        Item("Big Shot", 2),
        Item("Average Joe (Remix)", 3),
        Item(None, 4),
    ]
    assert [i.order for i in best_songs_first(items)] == [0, 2, 4, 1, 3]
