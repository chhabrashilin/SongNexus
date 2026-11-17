"""Around you aggregation: privacy floors at their exact limits, ranges, movement, rising."""

from datetime import UTC, datetime, timedelta

import pytest

from songnexus.core import community as c

NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)
RECENTLY = NOW - timedelta(days=1)
LONG_AGO = NOW - timedelta(days=30)


def tallies(
    members: int, artist: str, *, start: int = 0, plays: int = 5, last: datetime | None = RECENTLY
) -> list[c.Tally]:
    return [c.Tally(m, artist, plays, last) for m in range(start, start + members)]


def chart(rows: list[c.Tally], now: datetime = NOW, genres: dict[str, list[str]] | None = None):
    return c.compute_chart(
        rows,
        known=lambda a: a != "unknown",
        genres_of=lambda a: (genres or {}).get(a, []),
        now=now,
    )


# --- ranges ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, None),
        (2, None),
        (3, c.Range(3, 4)),
        (4, c.Range(3, 4)),
        (5, c.Range(5, 9)),
        (9, c.Range(5, 9)),
        (10, c.Range(10, 24)),
        (24, c.Range(10, 24)),
        (25, c.Range(25, 49)),
        (9999, c.Range(5000, 9999)),
        (10000, c.Range(10000, None)),
        (10**7, c.Range(10000, None)),
    ],
)
def test_band_edges(count: int, expected: c.Range | None) -> None:
    assert c.band(count) == expected


def test_no_band_reveals_an_exact_small_count() -> None:
    for count in range(3, 200):
        found = c.band(count)
        assert found is not None
        assert found.high is None or found.high > found.low


# --- the chart floor ------------------------------------------------------------------


def test_nine_members_lock_the_chart_and_say_how_many_more() -> None:
    result = chart(tallies(9, "a"))
    assert not result.unlocked
    assert result.listeners_needed == 1
    assert result.artists == ()
    assert result.genres == ()


def test_exactly_ten_members_unlock_it() -> None:
    result = chart(tallies(10, "a"))
    assert result.unlocked
    assert result.listeners_needed == 0
    assert [a.artist_id for a in result.artists] == ["a"]


def test_an_empty_community_needs_ten() -> None:
    assert chart([]).listeners_needed == c.MIN_CHART_LISTENERS


def test_members_without_catalog_listening_do_not_count() -> None:
    rows = [*tallies(9, "a"), c.Tally(9, "unknown", 50, RECENTLY), c.Tally(10, "a", 0, RECENTLY)]
    result = chart(rows)
    assert result.eligible == 9
    assert not result.unlocked


# --- the artist floor -----------------------------------------------------------------


def test_an_artist_needs_exactly_three_listeners() -> None:
    rows = tallies(10, "base") + tallies(3, "three") + tallies(2, "two", start=5)
    ids = [a.artist_id for a in chart(rows).artists]
    assert "three" in ids
    assert "two" not in ids


def test_one_heavy_listener_cannot_put_an_artist_on_the_chart() -> None:
    rows = [*tallies(10, "base"), c.Tally(0, "solo", 10000, RECENTLY)]
    assert [a.artist_id for a in chart(rows).artists] == ["base"]


def test_artists_rank_by_listeners_then_plays() -> None:
    rows = (
        tallies(10, "most")
        + tallies(4, "fewer-but-loud", plays=100)
        + tallies(5, "more-quiet", plays=1)
        + tallies(5, "more-loud", start=5, plays=3)
    )
    result = chart(rows)
    assert [(a.artist_id, a.rank) for a in result.artists] == [
        ("most", 1),
        ("more-loud", 2),
        ("more-quiet", 3),
        ("fewer-but-loud", 4),
    ]


def test_the_chart_is_capped() -> None:
    rows = [t for i in range(c.MAX_CHART_ARTISTS + 5) for t in tallies(10, f"artist-{i:03}")]
    assert len(chart(rows).artists) == c.MAX_CHART_ARTISTS


def test_genres_follow_the_same_floor_and_count_distinct_listeners() -> None:
    rows = tallies(10, "a") + tallies(3, "b") + tallies(2, "c", start=7)
    genres = {"a": ["rock"], "b": ["jazz", "rock"], "c": ["polka"]}
    result = chart(rows, genres=genres)
    assert [(g.genre_id, g.listeners) for g in result.genres] == [("rock", 10), ("jazz", 3)]


def test_only_an_artists_strongest_genres_count() -> None:
    genres = {"a": ["g1", "g2", "g3", "g4"]}
    result = chart(tallies(10, "a"), genres=genres)
    assert [g.genre_id for g in result.genres] == ["g1", "g2", "g3"]


def test_payload_round_trip() -> None:
    result = chart(tallies(10, "a") + tallies(3, "b"), genres={"a": ["rock"]})
    assert c.Chart.from_payload(result.to_payload(), NOW) == result


# --- movement and rising --------------------------------------------------------------


def _week_ago(rows: list[c.Tally]) -> c.Chart:
    return chart(rows, now=NOW - timedelta(days=8))


def test_no_movement_without_a_chart_a_week_old() -> None:
    current = chart(tallies(10, "a"))
    yesterday = chart(tallies(10, "a"), now=NOW - timedelta(days=1))
    assert c.baseline([yesterday], NOW) is None
    assert c.movements(current, None) is None


def test_movement_against_last_week() -> None:
    before = _week_ago(tallies(10, "a") + tallies(5, "b") + tallies(4, "c"))
    now = chart(tallies(10, "b") + tallies(6, "a") + tallies(4, "c") + tallies(3, "d"))
    moves = c.movements(now, c.baseline([before], NOW))
    assert moves == {
        "b": c.Movement(c.Direction.UP, 1),
        "a": c.Movement(c.Direction.DOWN, 1),
        "c": c.Movement(c.Direction.SAME),
        "d": c.Movement(c.Direction.NEW),
    }


def test_rising_needs_history_growth_and_recent_listeners() -> None:
    before = _week_ago(tallies(10, "base") + tallies(4, "grew") + tallies(4, "flat"))
    current = chart(
        tallies(10, "base")
        + tallies(6, "grew")  # 4 -> 6: +2 and +50%
        + tallies(4, "flat")
        + tallies(3, "new")  # not on last week's chart: 0 -> 3
        + tallies(3, "stale", start=3, last=LONG_AGO)  # grew, but nobody played it this week
    )
    assert c.rising(current, [before], NOW) == ["new", "grew"]
    assert c.rising(current, [], NOW) == []


def test_rising_ignores_charts_outside_the_28_day_window() -> None:
    too_old = chart(tallies(10, "base") + tallies(3, "a"), now=NOW - timedelta(days=40))
    current = chart(tallies(10, "base") + tallies(6, "a"))
    assert c.rising(current, [too_old], NOW) == []


def test_rising_compares_with_the_peak_of_the_window() -> None:
    peak = _week_ago(tallies(10, "base") + tallies(6, "a"))
    dip = chart(tallies(10, "base") + tallies(3, "a"), now=NOW - timedelta(days=20))
    current = chart(tallies(10, "base") + tallies(6, "a"))
    assert c.rising(current, [peak, dip], NOW) == []


# --- directory search -----------------------------------------------------------------


def _directory() -> c.Directory:
    def campus(cid: str, name: str, short: str, city: str, size: int) -> c.Community:
        return c.Community(
            cid, c.Kind.CAMPUS, name, short, city, "US-WI", "US", "", "Q1", None, size
        )

    return c.Directory(
        (
            campus("uw", "University of Wisconsin–Madison", "UW–Madison", "Madison", 45000),
            campus("uwm", "University of Wisconsin–Milwaukee", "UWM", "Milwaukee", 24000),
            c.Community(
                "madison", c.Kind.CITY, "Madison", "Madison", "Madison", "US-WI", "US", "", "Q2"
            ),
        ),
        version="v",
    )


def test_search_matches_word_prefixes_in_any_order() -> None:
    directory = _directory()
    assert [x.id for x in directory.search("uw mad")] == ["uw"]
    assert [x.id for x in directory.search("madison wisconsin")] == ["uw"]
    assert [x.id for x in directory.search("wisconsin")] == ["uw", "uwm"]


def test_search_filters_by_kind_and_ranks_exact_names_first() -> None:
    directory = _directory()
    assert [x.id for x in directory.search("madison", c.Kind.CITY)] == ["madison"]
    assert next(x.id for x in directory.search("madison")) == "madison"
    assert [x.id for x in directory.search("")] == ["uw", "uwm", "madison"]
