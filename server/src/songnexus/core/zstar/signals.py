"""What a listener's data says: weighted seed artists, a genre profile and the negatives.

Every signal decays with age (an exponential half-life per kind), so the feed
follows what someone is into now. Weights are relative; they are documented
here and in docs/design/for-you.md, and tuned offline (``evaluate``).

Explicit signals outrank implicit ones: a follow or a Top 5 pick is a stated
preference; a click is evidence. Negative signals never become seeds: they
filter candidates (``not_interested``, ``blocked``) and feed ranking penalties
(``negative_artists``, ``genre_penalty``).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

DAY = timedelta(days=1)

# Seed weights before decay.
FOLLOW_WEIGHT = 3.0
TOP_ARTIST_WEIGHT = 4.0
MORE_LIKE_WEIGHT = 3.0
LISTEN_WEIGHT = 2.0  # "Listen on YouTube Music" from the app
OPEN_WEIGHT = 1.0  # opened an artist (feed card, page view)
DWELL_WEIGHT = 1.0  # at most this much for long attention on a feed card
DWELL_FULL_MS = 30_000

# Half-lives.
FOLLOW_HALF_LIFE = 365 * DAY
MORE_LIKE_HALF_LIFE = 90 * DAY
ENGAGEMENT_HALF_LIFE = 30 * DAY
LISTENING_HALF_LIFE = 120 * DAY

# How long a "not interested" keeps an artist out of the feed, and how long a
# "less of this genre" lowers the genre.
NOT_INTERESTED_FOR = 180 * DAY
LESS_GENRE_HALF_LIFE = 90 * DAY

MAX_SEEDS = 60
# Artists the listener already knows well are not recommended back to them.
KNOWN_PLAYS = 10


def decay(age: timedelta, half_life: timedelta) -> float:
    """Weight multiplier for a signal ``age`` old: 1 when new, 1/2 after one half-life."""
    seconds = max(age.total_seconds(), 0.0)
    return math.pow(0.5, seconds / half_life.total_seconds())


def play_weight(plays: int) -> float:
    """1 + ln(plays): one heavily played artist cannot drown out the rest."""
    return 1.0 + math.log(max(plays, 1))


@dataclass(frozen=True)
class Engagement:
    """A listener's activity with one artist in the retention window.

    Attributes:
        impressions: Feed cards seen (at least half visible for a second).
        opens: Artist opened (from the feed or anywhere in the app).
        listens: "Listen on YouTube Music" pressed.
        skips: Cards scrolled past quickly.
        dwell_ms: Total attention on feed cards.
        last_at: The most recent of these.
        recent_impressions: Impressions in the fatigue window (``FATIGUE_WINDOW``).
    """

    impressions: int = 0
    opens: int = 0
    listens: int = 0
    skips: int = 0
    dwell_ms: int = 0
    last_at: datetime | None = None
    recent_impressions: int = 0


@dataclass(frozen=True)
class Signals:
    """Everything known about one listener, as read from storage.

    Attributes:
        now: The request time; every decay is relative to it.
        follows: Artist -> when followed.
        plays: Artist -> (plays, last played) from linked services and imports.
        top_artists: The profile's Top 5, in order.
        preferred_genres: Genres picked in settings.
        more_like: Artist -> when "more like this" was pressed.
        not_interested: Artist -> when "not interested" was pressed.
        less_genres: Genre -> when "less of this genre" was pressed.
        blocked: Artists blocked everywhere.
        engagement: Artist -> activity.
        friends: Artist -> how many friends share it in their Top 5.
    """

    now: datetime
    follows: Mapping[str, datetime] = field(default_factory=dict)
    plays: Mapping[str, tuple[int, datetime | None]] = field(default_factory=dict)
    top_artists: Sequence[str] = ()
    preferred_genres: Sequence[str] = ()
    more_like: Mapping[str, datetime] = field(default_factory=dict)
    not_interested: Mapping[str, datetime] = field(default_factory=dict)
    less_genres: Mapping[str, datetime] = field(default_factory=dict)
    blocked: frozenset[str] = frozenset()
    engagement: Mapping[str, Engagement] = field(default_factory=dict)
    friends: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Profile:
    """The listener as the recommender sees them.

    Attributes:
        seeds: Artist -> weight, heaviest first, at most ``MAX_SEEDS``.
        seed_reasons: Artist -> why it is a seed (``FOLLOW``, ``TOP``, ``PLAYS``,
            ``MORE_LIKE``, ``ENGAGED``), the strongest contribution.
        excluded: Artists never to recommend now (blocked, not interested,
            followed, known well).
        negative_artists: Artist -> weight of a recent "not interested".
        genre_penalty: Genre -> weight of a recent "less of this genre".
        preferred_genres: Genres picked in settings.
        cold: True when there is nothing to personalize from.
    """

    seeds: dict[str, float]
    seed_reasons: dict[str, str]
    excluded: frozenset[str]
    negative_artists: dict[str, float]
    genre_penalty: dict[str, float]
    preferred_genres: tuple[str, ...]
    cold: bool


def build_profile(signals: Signals) -> Profile:
    """Turns raw signals into seeds, exclusions and penalties."""
    now = signals.now
    weights: dict[str, float] = defaultdict(float)
    contributions: dict[str, dict[str, float]] = defaultdict(dict)

    def add(artist_id: str, reason: str, value: float) -> None:
        if value <= 0:
            return
        weights[artist_id] += value
        contributions[artist_id][reason] = contributions[artist_id].get(reason, 0.0) + value

    for artist_id, at in signals.follows.items():
        add(artist_id, "FOLLOW", FOLLOW_WEIGHT * max(decay(now - at, FOLLOW_HALF_LIFE), 0.5))
    for rank, artist_id in enumerate(signals.top_artists):
        add(artist_id, "TOP", TOP_ARTIST_WEIGHT * (1.0 - 0.1 * rank))
    for artist_id, (plays, last) in signals.plays.items():
        recency = 1.0 if last is None else max(decay(now - last, LISTENING_HALF_LIFE), 0.25)
        add(artist_id, "PLAYS", play_weight(plays) * recency)
    for artist_id, at in signals.more_like.items():
        add(artist_id, "MORE_LIKE", MORE_LIKE_WEIGHT * decay(now - at, MORE_LIKE_HALF_LIFE))
    for artist_id, e in signals.engagement.items():
        if e.last_at is None:
            continue
        recency = decay(now - e.last_at, ENGAGEMENT_HALF_LIFE)
        attention = DWELL_WEIGHT * min(e.dwell_ms / DWELL_FULL_MS, 1.0)
        value = (LISTEN_WEIGHT * e.listens + OPEN_WEIGHT * e.opens) ** 0.5 + attention
        add(artist_id, "ENGAGED", value * recency)

    not_interested = {
        a: decay(now - at, NOT_INTERESTED_FOR / 2)
        for a, at in signals.not_interested.items()
        if now - at < NOT_INTERESTED_FOR
    }
    for artist_id in list(weights):
        if artist_id in signals.blocked or artist_id in not_interested:
            del weights[artist_id]

    top = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_SEEDS]
    seeds = dict(top)
    reasons = {a: max(contributions[a].items(), key=lambda kv: (kv[1], kv[0]))[0] for a in seeds}
    known = {a for a, (plays, _) in signals.plays.items() if plays >= KNOWN_PLAYS}
    excluded = (
        frozenset(signals.blocked)
        | frozenset(not_interested)
        | frozenset(signals.follows)
        | frozenset(signals.top_artists)
        | frozenset(known)
    )
    genre_penalty = {
        g: decay(now - at, LESS_GENRE_HALF_LIFE)
        for g, at in signals.less_genres.items()
        if decay(now - at, LESS_GENRE_HALF_LIFE) > 0.05  # noqa: PLR2004 - negligible below 5 %
    }
    return Profile(
        seeds=seeds,
        seed_reasons=reasons,
        excluded=excluded,
        negative_artists=not_interested,
        genre_penalty=genre_penalty,
        preferred_genres=tuple(signals.preferred_genres),
        cold=not seeds and not signals.preferred_genres,
    )
