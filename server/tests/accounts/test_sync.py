"""Sync keeps per-artist aggregates only."""

from collections.abc import Callable, Sequence

from songnexus.accounts.connectors import Play
from songnexus.accounts.sync import Tally, aggregate, merge
from songnexus.core import ids

KENDRICK = ids.artist_id("mb-k")
SZA = "sza-id"


def _resolver(calls: list[Sequence[str]]) -> Callable[[Sequence[str]], list[str | None]]:
    def resolve(names: Sequence[str]) -> list[str | None]:
        calls.append(list(names))
        return [SZA if n == "SZA" else None for n in names]

    return resolve


def test_mbids_resolve_directly_and_names_through_the_matcher_once() -> None:
    calls: list[Sequence[str]] = []
    result = aggregate(
        [
            Play("Kendrick Lamar", "mb-k", 100),
            Play("K. Lamar (typo)", "mb-k", 300),
            Play("SZA", None, 200),
            Play("SZA", None, 250),
            Play("Somebody Unknown", None, 50),
        ],
        known_artists=lambda a: a == KENDRICK,
        resolve_names=_resolver(calls),
    )
    assert calls == [["SZA", "Somebody Unknown"]]  # distinct names, MBID plays excluded
    assert result.tallies == {KENDRICK: Tally(2, 300), SZA: Tally(2, 250)}
    assert result.unmatched_plays == 1


def test_plays_without_times_still_count() -> None:
    result = aggregate([Play("SZA")], known_artists=lambda _a: False, resolve_names=_resolver([]))
    assert result.tallies == {SZA: Tally(1, None)}


def test_merge_adds_counts_and_keeps_the_latest_time() -> None:
    assert merge(Tally(3, 100), Tally(2, 90)) == Tally(5, 100)
    assert merge(None, Tally(1, None)) == Tally(1, None)
    assert merge(Tally(1, None), Tally(1, None)) == Tally(2, None)
