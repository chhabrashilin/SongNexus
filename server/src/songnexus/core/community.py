"""Around you: campus and city charts from opted-in listeners (privacy-first aggregation).

A *community* is a campus (a university) or a city. Listeners opt in to at most one
of each; a community's chart aggregates its members' linked-account tallies
(plays per artist). Nothing here sees who a member is: members arrive as opaque
keys and leave only as counts.

Privacy rules (k-anonymity), enforced here and nowhere weaker:

* A chart exists only when at least ``MIN_CHART_LISTENERS`` members have
  listening data. Below that, the only number shown is how many more are needed.
* An artist (or genre) row exists only when at least ``MIN_ARTIST_LISTENERS``
  distinct members listened.
* Counts leave the server as ranges (``band``), never as exact small numbers;
  plays are used only to order artists with the same number of listeners.

Rising: tallies keep a single "last played" time per artist, not a play history,
so this week's plays can't be told apart from older ones per listener. Rising
therefore compares the chart with stored charts from the 28 days before this
week: an artist is rising when its listeners grew clearly past the most it had
in that window, and at least ``MIN_ARTIST_LISTENERS`` members played it in the
last 7 days. Until a week of chart history exists, nothing is marked rising.
"""

from __future__ import annotations

import enum
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

from songnexus.core.text import normalize

MIN_CHART_LISTENERS = 10
MIN_ARTIST_LISTENERS = 3
MAX_CHART_ARTISTS = 50
MAX_CHART_GENRES = 12
MAX_RISING = 10
# Genres counted per artist: its strongest few, so one artist with many tags
# doesn't dominate the genre list.
GENRES_PER_ARTIST = 3
RECENT = timedelta(days=7)
HISTORY = timedelta(days=28)
# Rising: listeners at least 25% and 2 above the peak in the history window.
RISING_GROWTH = 1.25
RISING_MIN_GAIN = 2
# Lower bounds of the ranges counts are shown in. The first is the artist floor.
BANDS: tuple[int, ...] = (3, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)


class Kind(enum.StrEnum):
    """What a community is."""

    CAMPUS = "CAMPUS"
    CITY = "CITY"


@dataclass(frozen=True)
class Community:
    """A campus or city listeners can join.

    Attributes:
        id: Stable slug (``university-of-wisconsin-madison``, ``madison-us-wi``).
        kind: Campus or city.
        name: Display name.
        short_name: Short display name ("UW–Madison"); the name when there is none.
        city: The city's display name (a campus's city; a city's own name).
        region: ISO 3166-2 subdivision code ("US-WI"), or "" when unknown.
        country: ISO 3166-1 alpha-2 code ("US").
        website: The official website's domain ("wisc.edu"), or "".
        wikidata: The Wikidata item ("Q838330") the entry was built from.
        city_id: For a campus, the ID of its city community, if it has one.
        size: Students (campus) or population (city); orders search results.
    """

    id: str
    kind: Kind
    name: str
    short_name: str
    city: str
    region: str
    country: str
    website: str
    wikidata: str
    city_id: str | None = None
    size: int = 0
    synthetic: bool = False
    keys: tuple[str, ...] = field(init=False, compare=False, repr=False)
    names: tuple[str, ...] = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        """Precomputes the normalized strings a search matches against."""
        keys = {
            normalize(v)
            for v in (self.name, self.short_name, self.city, self.country, self.region)
            if v
        }
        if self.website:
            keys.add(normalize(self.website.split(".")[0]))
        object.__setattr__(self, "keys", tuple(sorted(k for k in keys if k)))
        names = {normalize(self.name), normalize(self.short_name)}
        object.__setattr__(self, "names", tuple(sorted(n for n in names if n)))


@dataclass(frozen=True)
class Directory:
    """Every community listeners can join, from the curated data file."""

    communities: tuple[Community, ...]
    version: str
    by_id: Mapping[str, Community] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.by_id:
            object.__setattr__(self, "by_id", {c.id: c for c in self.communities})

    def search(self, query: str, kind: Kind | None = None) -> list[Community]:
        """Returns communities matching ``query``, best first.

        Every word of the query must start a word of the name, short name, city
        or website (so "uw mad" finds UW–Madison). Exact short names come first,
        then name prefixes, then the largest. An empty query lists everything,
        largest first.
        """
        words = normalize(query).split()
        scored: list[tuple[int, int, str, Community]] = []
        for community in self.communities:
            if kind is not None and community.kind is not kind:
                continue
            keys = community.keys
            if words:
                tokens = {t for k in keys for t in k.split()}
                if not all(any(t.startswith(w) for t in tokens) for w in words):
                    continue
                joined = " ".join(words)
                if joined in community.names:
                    score = 0
                elif any(k.startswith(joined) for k in keys):
                    score = 1
                else:
                    score = 2
            else:
                score = 0
            scored.append((score, -community.size, community.name, community))
        scored.sort(key=lambda s: s[:3])
        return [s[3] for s in scored]


@dataclass(frozen=True)
class Range:
    """A count shown as a range: ``low`` to ``high`` inclusive (``high`` None: or more)."""

    low: int
    high: int | None


def band(count: int) -> Range | None:
    """Returns the range ``count`` is shown as, or None below the artist floor."""
    if count < BANDS[0]:
        return None
    for low, nxt in pairwise(BANDS):
        if count < nxt:
            return Range(low, nxt - 1)
    return Range(BANDS[-1], None)


@dataclass(frozen=True)
class Tally:
    """One member's plays of one artist (summed across their linked services).

    ``member`` is an opaque key that never leaves the aggregation.
    """

    member: int
    artist_id: str
    plays: int
    last_played_at: datetime | None


@dataclass(frozen=True)
class ArtistRow:
    """A chart artist. The exact counts are internal: they are served only as ranges."""

    artist_id: str
    rank: int
    listeners: int
    plays: int
    recent_listeners: int


@dataclass(frozen=True)
class GenreRow:
    """A chart genre with the members who listen to any of its artists (internal count)."""

    genre_id: str
    listeners: int


@dataclass(frozen=True)
class Chart:
    """One community's chart at one time.

    Attributes:
        eligible: Members with listening data (in the catalog) when computed.
        artists: Ranked artists, each with at least ``MIN_ARTIST_LISTENERS`` listeners.
            Empty while the chart is locked.
        genres: Ranked genres under the same floor. Empty while locked.
        computed_at: When it was computed.
        demo: True when synthetic development members contributed.
    """

    eligible: int
    artists: tuple[ArtistRow, ...]
    genres: tuple[GenreRow, ...]
    computed_at: datetime
    demo: bool = False

    @property
    def unlocked(self) -> bool:
        """True when enough members have listening data to show the chart."""
        return self.eligible >= MIN_CHART_LISTENERS

    @property
    def listeners_needed(self) -> int:
        """How many more members with listening data unlock the chart (0 when unlocked)."""
        return max(0, MIN_CHART_LISTENERS - self.eligible)

    def to_payload(self) -> dict[str, Any]:
        """Serializes for storage (server-side only; it holds internal counts)."""
        return {
            "eligible": self.eligible,
            "demo": self.demo,
            "artists": [
                [a.artist_id, a.rank, a.listeners, a.plays, a.recent_listeners]
                for a in self.artists
            ],
            "genres": [[g.genre_id, g.listeners] for g in self.genres],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], computed_at: datetime) -> Chart:
        """Restores a stored chart."""
        return cls(
            eligible=int(payload.get("eligible", 0)),
            artists=tuple(
                ArtistRow(str(a), int(r), int(n), int(p), int(rn))
                for a, r, n, p, rn in payload.get("artists", [])
            ),
            genres=tuple(GenreRow(str(g), int(n)) for g, n in payload.get("genres", [])),
            computed_at=computed_at,
            demo=bool(payload.get("demo", False)),
        )


def compute_chart(
    tallies: Iterable[Tally],
    *,
    known: Callable[[str], bool],
    genres_of: Callable[[str], Sequence[str]],
    now: datetime,
    demo: bool = False,
) -> Chart:
    """Aggregates members' tallies into a chart, applying every privacy floor.

    Args:
        tallies: Every member's tallies (any order). Members without tallies
            simply don't appear, and don't count as having listening data.
        known: Whether an artist is in the catalog; others are ignored.
        genres_of: An artist's genre IDs, strongest first.
        now: The time "recent" is measured from.
        demo: Marks the chart as containing synthetic development data.
    """
    listeners: dict[str, set[int]] = defaultdict(set)
    recent: dict[str, set[int]] = defaultdict(set)
    plays: dict[str, int] = defaultdict(int)
    members: set[int] = set()
    for tally in tallies:
        if tally.plays <= 0 or not known(tally.artist_id):
            continue
        members.add(tally.member)
        listeners[tally.artist_id].add(tally.member)
        plays[tally.artist_id] += tally.plays
        last = tally.last_played_at
        if last is not None and _aware(last, now) >= now - RECENT:
            recent[tally.artist_id].add(tally.member)
    if len(members) < MIN_CHART_LISTENERS:
        return Chart(len(members), (), (), now, demo)

    eligible_artists = [a for a, who in listeners.items() if len(who) >= MIN_ARTIST_LISTENERS]
    eligible_artists.sort(key=lambda a: (-len(listeners[a]), -plays[a], a))
    artists = tuple(
        ArtistRow(a, rank, len(listeners[a]), plays[a], len(recent[a]))
        for rank, a in enumerate(eligible_artists[:MAX_CHART_ARTISTS], start=1)
    )

    genre_listeners: dict[str, set[int]] = defaultdict(set)
    for artist_id, who in listeners.items():
        for genre_id in list(genres_of(artist_id))[:GENRES_PER_ARTIST]:
            genre_listeners[genre_id] |= who
    ranked_genres = sorted(
        (g for g, who in genre_listeners.items() if len(who) >= MIN_ARTIST_LISTENERS),
        key=lambda g: (-len(genre_listeners[g]), g),
    )
    genres = tuple(GenreRow(g, len(genre_listeners[g])) for g in ranked_genres[:MAX_CHART_GENRES])
    return Chart(len(members), artists, genres, now, demo)


def _aware(value: datetime, like: datetime) -> datetime:
    """Gives a naive timestamp (SQLite) the timezone of ``like``."""
    return (
        value
        if value.tzinfo is not None or like.tzinfo is None
        else value.replace(tzinfo=like.tzinfo)
    )


class Direction(enum.StrEnum):
    """How an artist moved since the chart a week ago."""

    UP = "UP"
    DOWN = "DOWN"
    SAME = "SAME"
    NEW = "NEW"


@dataclass(frozen=True)
class Movement:
    """An artist's movement: direction and places moved (0 for SAME and NEW)."""

    direction: Direction
    places: int = 0


def baseline(history: Sequence[Chart], now: datetime) -> Chart | None:
    """Returns the newest unlocked chart at least a week old, from ``history``."""
    old = [c for c in history if c.unlocked and _aware(c.computed_at, now) <= now - RECENT]
    return max(old, key=lambda c: _aware(c.computed_at, now), default=None)


def movements(current: Chart, previous: Chart | None) -> dict[str, Movement] | None:
    """Returns each current artist's movement against ``previous`` (None: no baseline)."""
    if previous is None:
        return None
    before = {a.artist_id: a.rank for a in previous.artists}
    result: dict[str, Movement] = {}
    for row in current.artists:
        old = before.get(row.artist_id)
        if old is None:
            result[row.artist_id] = Movement(Direction.NEW)
        elif old > row.rank:
            result[row.artist_id] = Movement(Direction.UP, old - row.rank)
        elif old < row.rank:
            result[row.artist_id] = Movement(Direction.DOWN, row.rank - old)
        else:
            result[row.artist_id] = Movement(Direction.SAME)
    return result


def rising(current: Chart, history: Sequence[Chart], now: datetime) -> list[str]:
    """Returns the rising artists, most rising first (see the module docstring).

    ``history`` may hold any stored charts; only unlocked ones from the 28 days
    before this week count.
    """
    window = [
        c
        for c in history
        if c.unlocked and now - RECENT - HISTORY <= _aware(c.computed_at, now) <= now - RECENT
    ]
    if not window or not current.unlocked:
        return []
    peak: dict[str, int] = defaultdict(int)
    for chart in window:
        for row in chart.artists:
            peak[row.artist_id] = max(peak[row.artist_id], row.listeners)
    candidates: list[tuple[float, int, str]] = []
    for row in current.artists:
        if row.recent_listeners < MIN_ARTIST_LISTENERS:
            continue
        before = peak.get(row.artist_id, 0)
        if row.listeners >= max(before * RISING_GROWTH, before + RISING_MIN_GAIN):
            growth = (row.listeners - before) / max(before, 1)
            candidates.append((-growth, row.rank, row.artist_id))
    candidates.sort()
    return [artist_id for _, _, artist_id in candidates[:MAX_RISING]]


MAX_MOVERS = 10


@dataclass(frozen=True)
class Mover:
    """An artist that moved between two charts. A rank is None where it was not charted."""

    artist_id: str
    rank: int | None
    previous_rank: int | None

    @property
    def places(self) -> int:
        """Places moved (0 when it entered or left)."""
        if self.rank is None or self.previous_rank is None:
            return 0
        return abs(self.previous_rank - self.rank)


@dataclass(frozen=True)
class WeeklyMovers:
    """The weekly recap of a chart: what rose, fell, entered and left since ``previous``."""

    rose: tuple[Mover, ...]
    fell: tuple[Mover, ...]
    entered: tuple[Mover, ...]
    left: tuple[Mover, ...]


def weekly_movers(current: Chart, previous: Chart) -> WeeklyMovers:
    """Compares two stored charts (both already past the privacy floors).

    Biggest moves first; entries by their new rank, exits by their old rank.
    Each list holds at most ``MAX_MOVERS``.
    """
    before = {a.artist_id: a.rank for a in previous.artists}
    now_ranks = {a.artist_id: a.rank for a in current.artists}
    moved = [Mover(a, r, before.get(a)) for a, r in now_ranks.items()]
    rose = sorted(
        (m for m in moved if m.previous_rank is not None and m.previous_rank > (m.rank or 0)),
        key=lambda m: (-m.places, m.rank),
    )
    fell = sorted(
        (m for m in moved if m.previous_rank is not None and m.previous_rank < (m.rank or 0)),
        key=lambda m: (-m.places, m.rank),
    )
    entered = sorted((m for m in moved if m.previous_rank is None), key=lambda m: m.rank or 0)
    left = sorted(
        (Mover(a, None, r) for a, r in before.items() if a not in now_ranks),
        key=lambda m: m.previous_rank or 0,
    )
    return WeeklyMovers(
        tuple(rose[:MAX_MOVERS]),
        tuple(fell[:MAX_MOVERS]),
        tuple(entered[:MAX_MOVERS]),
        tuple(left[:MAX_MOVERS]),
    )
