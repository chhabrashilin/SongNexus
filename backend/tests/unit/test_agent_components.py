"""Planner intent parsing, grounding checks, rate limiting, metrics."""

from __future__ import annotations

import pytest

from songnexus.agent.grounding import unsupported_mentions
from songnexus.agent.planner import classify
from songnexus.api.ratelimit import RateLimiter
from songnexus.core.errors import RateLimitedError
from songnexus.core.metrics import MetricsRegistry
from songnexus.search.index import SearchDoc, SearchIndex


@pytest.mark.parametrize(
    ("question", "intent", "names"),
    [
        ("How is Miles Davis connected to Drake?", "connection", ("Miles Davis", "Drake")),
        ("How are Kendrick Lamar and SZA connected?", "connection", ("Kendrick Lamar", "SZA")),
        (
            "What's the connection between Daft Punk and Kamasi Washington?",
            "connection",
            ("Daft Punk", "Kamasi Washington"),
        ),
        ("degrees of separation between A and B", "connection", ("A", "B")),
        ("Connect Taylor Swift and Kendrick Lamar", "connection", ("Taylor Swift", "Kendrick Lamar")),
        ("Who has SZA worked with?", "collaborators", ("SZA",)),
        ("collaborators of Thundercat", "collaborators", ("Thundercat",)),
        ("Who produced for Kendrick Lamar?", "producers", ("Kendrick Lamar",)),
        ("Find artists who connect jazz and hip-hop", "genre_bridges", ("jazz", "hip-hop")),
        ("Which artists bridge different scenes?", "bridges", ()),
        ("Who are the most connected artists?", "central", ()),
        ("Tell me about Thundercat", "about", ("Thundercat",)),
        ("What is the best pizza in Madison?", None, ()),
        ("Compare Kendrick Lamar and Drake", None, ()),
    ],
)
def test_classify(question: str, intent: str | None, names: tuple[str, ...]) -> None:
    assert classify(question) == (intent, names)


@pytest.fixture
def index() -> SearchIndex:
    idx = SearchIndex()
    for entity_id, name, aliases in [
        ("k", "Kendrick Lamar", ["Kendrick Lamar, SZA"]),  # real MusicBrainz alias quirk
        ("s", "SZA", []),
        ("d", "Drake", []),
        ("l", "Like", []),  # an artist whose name is a common word
    ]:
        idx.add(SearchDoc("artist", entity_id, name), names=[name], aliases=aliases)
    return idx.freeze()


def test_mentions_returned_by_tools_are_supported(index: SearchIndex) -> None:
    answer = "Kendrick Lamar is featured on SZA's “Doves in the Wind”."
    assert unsupported_mentions(answer, "q", {"k", "s"}, {"Kendrick Lamar", "SZA"}, index) == []


def test_unreturned_artist_is_flagged(index: SearchIndex) -> None:
    answer = "Kendrick Lamar also worked with Drake."
    assert unsupported_mentions(answer, "q", {"k"}, {"Kendrick Lamar"}, index) == ["Drake"]


def test_artist_named_by_the_user_is_not_flagged(index: SearchIndex) -> None:
    answer = "I could not find Drake in the loaded data."
    assert unsupported_mentions(answer, "How is Drake connected to X?", set(), set(), index) == []


def test_quoted_titles_and_arrows_do_not_create_false_mentions(index: SearchIndex) -> None:
    answer = "1. Kendrick Lamar → SZA: SZA's “Garden (Say It Like Dat)”"
    assert unsupported_mentions(answer, "q", {"k", "s"}, {"Kendrick Lamar", "SZA"}, index) == []


def test_lowercase_common_words_are_ignored(index: SearchIndex) -> None:
    assert unsupported_mentions("they like each other", "q", set(), set(), index) == []


def test_rate_limiter_refills_over_time() -> None:
    now = [0.0]
    limiter = RateLimiter(per_minute=2, clock=lambda: now[0])
    limiter.check("ip")
    limiter.check("ip")
    with pytest.raises(RateLimitedError) as err:
        limiter.check("ip")
    assert err.value.details["retry_after_s"] > 0
    limiter.check("other-ip")  # buckets are per client
    now[0] = 30.0  # half a minute refills one token
    limiter.check("ip")


def test_metrics_quantiles() -> None:
    registry = MetricsRegistry()
    for value in range(1, 101):
        registry.observe("x", float(value))
    registry.counter("c", 3)
    snap = registry.snapshot()
    summary = snap["latency_ms"]["x"]  # type: ignore[index]
    assert summary["count"] == 100
    assert summary["p50"] == pytest.approx(50, abs=1)
    assert summary["p95"] == pytest.approx(95, abs=1)
    assert snap["counters"] == {"c": 3}
