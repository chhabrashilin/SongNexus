"""Home shelves: ranked rows of artists, recordings and labels, each item with its reason.

Pure and deterministic: one catalog version (and, for "on this day", one date)
always yields the same shelves in the same order. Like stories, the server
writes no prose: a shelf is a message ID with parameters, and every item
carries a machine-readable reason (a kind and the counts behind it) so the
client can print "Produced 212 recordings" in the viewer's language, and the
count can be checked on the artist page.

Shelves are generated with more candidates than are shown (``CANDIDATES``), so
removing the artists a viewer blocked still leaves a full row.
"""

from __future__ import annotations

import enum
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from songnexus.core.browse import BrowseIndex, decade_of
from songnexus.core.model import CreditRole

CANDIDATES = 40  # per shelf, before blocked artists are removed
GENRE_SHELVES = 6
# A producer is "mostly behind the scenes" when they produced at least this many
# times as many recordings as they lead. Tuned so headliners who self-produce
# (credited as primary on most of what they produce) stay off the shelf.
BEHIND_THE_SCENES_RATIO = 2
MIN_PRODUCED = 5
MIN_GENRES_BRIDGED = 3
MIN_DECADE_RECORDINGS = 2

Param = str | int


class ShelfKind(enum.StrEnum):
    """Which kind of shelf."""

    BEHIND_THE_HITS = "BEHIND_THE_HITS"
    SUPER_CONNECTORS = "SUPER_CONNECTORS"
    GENRE_BRIDGES = "GENRE_BRIDGES"
    ON_THIS_DAY = "ON_THIS_DAY"
    GENRE = "GENRE"
    DECADE = "DECADE"
    LABELS = "LABELS"


SHELF_MESSAGES = {
    ShelfKind.BEHIND_THE_HITS: "shelf.behindTheHits",
    ShelfKind.SUPER_CONNECTORS: "shelf.superConnectors",
    ShelfKind.GENRE_BRIDGES: "shelf.genreBridges",
    ShelfKind.ON_THIS_DAY: "shelf.onThisDay",  # {month} {day}
    ShelfKind.GENRE: "shelf.genre",  # {genre}
    ShelfKind.DECADE: "shelf.decade",  # {decade}
    ShelfKind.LABELS: "shelf.labels",
}


class ReasonKind(enum.StrEnum):
    """Why an item is on a shelf."""

    PRODUCED_RECORDINGS = "PRODUCED_RECORDINGS"
    COLLABORATORS = "COLLABORATORS"
    GENRES_BRIDGED = "GENRES_BRIDGED"
    RELEASED_ON_DAY = "RELEASED_ON_DAY"
    CREDITED_RECORDINGS = "CREDITED_RECORDINGS"
    LABEL_RELEASES = "LABEL_RELEASES"


REASON_MESSAGES = {
    ReasonKind.PRODUCED_RECORDINGS: "reason.producedRecordings",  # {count} {performers} {led}
    ReasonKind.COLLABORATORS: "reason.collaborators",  # {count}
    ReasonKind.GENRES_BRIDGED: "reason.genresBridged",  # {count} {collaborators}
    ReasonKind.RELEASED_ON_DAY: "reason.releasedOnDay",  # {year} {yearsAgo}
    ReasonKind.CREDITED_RECORDINGS: "reason.creditedRecordings",  # {count} {decade} {role}
    ReasonKind.LABEL_RELEASES: "reason.labelReleases",  # {count} {artists}
}


@dataclass(frozen=True)
class Reason:
    """A machine-readable reason: a kind and the numbers behind it."""

    kind: ReasonKind
    params: tuple[tuple[str, Param], ...]

    @property
    def message_id(self) -> str:
        """The client message key."""
        return REASON_MESSAGES[self.kind]


def _reason(kind: ReasonKind, **params: Param) -> Reason:
    return Reason(kind, tuple(sorted(params.items())))


@dataclass(frozen=True)
class ShelfItem:
    """One item: exactly one of artist, recording or label, and its reason.

    Attributes:
        artist_id: The artist, for artist shelves.
        recording_id: The recording, for recording shelves.
        label_id: The label, for label shelves.
        reason: Why it is here.
        artist_ids: Every artist the item shows (to remove blocked ones).
    """

    reason: Reason
    artist_id: str | None = None
    recording_id: str | None = None
    label_id: str | None = None
    artist_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Shelf:
    """A shelf: its template, parameters and candidate items, best first.

    Attributes:
        id: Stable ID within a catalog version (``behind-the-hits``, ``genre-{id}``).
        kind: The shelf kind.
        params: Template values for the title.
        genre_id: The genre a GENRE shelf is about (its "see all" page).
        items: Candidates, best first; callers filter and cut to size.
    """

    id: str
    kind: ShelfKind
    params: tuple[tuple[str, Param], ...]
    items: tuple[ShelfItem, ...]
    genre_id: str | None = None

    @property
    def message_id(self) -> str:
        """The client message key for the shelf title."""
        return SHELF_MESSAGES[self.kind]


def _distinct_people(index: BrowseIndex, ranked: Iterable[str]) -> list[str]:
    """Keeps the first of an artist's identities (a person and their stage name)."""
    picked: list[str] = []
    covered: set[str] = set()
    for artist_id in ranked:
        if artist_id in covered:
            continue
        picked.append(artist_id)
        covered.add(artist_id)
        covered |= index.graph.other_identities([artist_id])
        if len(picked) == CANDIDATES:
            break
    return picked


def behind_the_hits(index: BrowseIndex) -> Shelf:
    """People with the most producer credits who mostly are not the headline performer."""
    producer, primary = CreditRole.PRODUCER.value, CreditRole.PRIMARY.value
    scored: list[tuple[int, int, str]] = []
    for artist_id, roles in index.recordings_by_role.items():
        produced = len(roles.get(producer, ()))
        led = len(roles.get(primary, ()))
        if produced >= MIN_PRODUCED and produced >= BEHIND_THE_SCENES_RATIO * led:
            scored.append((produced, led, artist_id))
    scored.sort(key=lambda s: (-s[0], index.graph.nodes[s[2]].name, s[2]))
    by_artist = {a: (p, led) for p, led, a in scored}
    items = []
    for artist_id in _distinct_people(index, (a for _, _, a in scored)):
        produced, led = by_artist[artist_id]
        performers = {
            a
            for r in index.recordings_by_role[artist_id][producer]
            for a in index.primary_artists.get(r, ())
            if a != artist_id
        }
        items.append(
            ShelfItem(
                _reason(
                    ReasonKind.PRODUCED_RECORDINGS,
                    count=produced,
                    performers=len(performers),
                    led=led,
                ),
                artist_id=artist_id,
                artist_ids=(artist_id,),
            )
        )
    return Shelf("behind-the-hits", ShelfKind.BEHIND_THE_HITS, (), tuple(items))


def super_connectors(index: BrowseIndex) -> Shelf:
    """Artists with the most distinct collaborators."""
    ranked = sorted((a for a, d in index.degree.items() if d > 0), key=index.connectedness_key)
    items = [
        ShelfItem(
            _reason(ReasonKind.COLLABORATORS, count=index.degree[a]),
            artist_id=a,
            artist_ids=(a,),
        )
        for a in _distinct_people(index, ranked)
    ]
    return Shelf("super-connectors", ShelfKind.SUPER_CONNECTORS, (), tuple(items))


def genre_bridges(index: BrowseIndex) -> Shelf:
    """Artists whose collaborators span the most distinct top-level genres.

    Each collaborator counts once, under its primary top-level genre;
    collaborators without genre data do not count.
    """
    bridged: dict[str, tuple[int, int]] = {}
    for artist_id, neighbors in index.adjacency.items():
        roots = [index.primary_root[n] for n in neighbors if n in index.primary_root]
        distinct = len(set(roots))
        if distinct >= MIN_GENRES_BRIDGED:
            bridged[artist_id] = (distinct, len(roots))
    ranked = sorted(bridged, key=lambda a: (-bridged[a][0], *index.connectedness_key(a)))
    items = [
        ShelfItem(
            _reason(ReasonKind.GENRES_BRIDGED, count=bridged[a][0], collaborators=bridged[a][1]),
            artist_id=a,
            artist_ids=(a,),
        )
        for a in _distinct_people(index, ranked)
    ]
    return Shelf("genre-bridges", ShelfKind.GENRE_BRIDGES, (), tuple(items))


def on_this_day(index: BrowseIndex, day: date) -> Shelf:
    """Recordings first released on the day's month and day, in earlier years.

    One recording per lead artist, best-connected artists first. Releases from the
    day's own year or later are left out ("on this day" looks back).
    """
    key = f"{day.month:02d}-{day.day:02d}"
    candidates = []
    for recording_id in index.by_month_day.get(key, ()):
        recording = index.recordings[recording_id]
        year = recording.year
        leads = index.primary_artists[recording_id]
        if year is None or year >= day.year or not leads:
            continue
        lead = min(leads, key=index.connectedness_key)
        candidates.append((index.connectedness_key(lead), year, recording_id, lead))
    candidates.sort()
    items = []
    seen_leads: set[str] = set()
    for _, year, recording_id, lead in candidates:
        if lead in seen_leads:
            continue
        seen_leads.add(lead)
        items.append(
            ShelfItem(
                _reason(ReasonKind.RELEASED_ON_DAY, year=year, yearsAgo=day.year - year),
                recording_id=recording_id,
                artist_ids=index.primary_artists[recording_id],
            )
        )
        if len(items) == CANDIDATES:
            break
    return Shelf(
        f"on-this-day-{key}",
        ShelfKind.ON_THIS_DAY,
        (("day", day.day), ("month", day.month)),
        tuple(items),
    )


def genre_shelves(index: BrowseIndex) -> list[Shelf]:
    """The most connected artists of the most populated top-level genres.

    Each shelf starts like its genre page; an artist already shown on an earlier
    genre shelf is skipped, so the shelves do not repeat each other.
    """
    shelves = []
    shown: set[str] = set()
    graph = index.graph
    for genre_id in index.top_level_genres()[:GENRE_SHELVES]:
        ranked = [a for a in index.genre_artists(genre_id) if a not in shown]
        picked = _distinct_people(index, ranked)
        shown.update(picked)
        shelves.append(
            Shelf(
                f"genre-{genre_id}",
                ShelfKind.GENRE,
                (("genre", graph.genre_names[genre_id]),),
                tuple(
                    ShelfItem(
                        _reason(ReasonKind.COLLABORATORS, count=index.degree[a]),
                        artist_id=a,
                        artist_ids=(a,),
                    )
                    for a in picked
                ),
                genre_id=genre_id,
            )
        )
    return shelves


def decade_shelves(index: BrowseIndex) -> list[Shelf]:
    """For each decade with data, the artists credited on the most recordings, newest first.

    Every credit role counts; the reason names the artist's most frequent role
    in that decade, so an engineer is labeled as one.
    """
    counts: dict[int, Counter[str]] = defaultdict(Counter)
    roles: dict[tuple[int, str], Counter[str]] = defaultdict(Counter)
    for artist_id, by_role in index.recordings_by_role.items():
        per_decade: dict[int, set[str]] = defaultdict(set)
        for role, recording_ids in by_role.items():
            for recording_id in recording_ids:
                year = index.recordings[recording_id].year
                if year is not None:
                    per_decade[decade_of(year)].add(recording_id)
                    roles[(decade_of(year), artist_id)][role] += 1
        for decade, recording_ids in per_decade.items():
            counts[decade][artist_id] = len(recording_ids)
    shelves = []
    graph = index.graph
    for decade in sorted(counts, reverse=True):
        ranked = sorted(
            (a for a, n in counts[decade].items() if n >= MIN_DECADE_RECORDINGS),
            key=lambda a: (-counts[decade][a], graph.nodes[a].name, a),
        )
        items = []
        for artist_id in _distinct_people(index, ranked):
            role_counts = roles[(decade, artist_id)]
            role = min(role_counts, key=lambda r: (-role_counts[r], r))
            items.append(
                ShelfItem(
                    _reason(
                        ReasonKind.CREDITED_RECORDINGS,
                        count=counts[decade][artist_id],
                        decade=decade,
                        role=role,
                    ),
                    artist_id=artist_id,
                    artist_ids=(artist_id,),
                )
            )
        shelves.append(
            Shelf(f"decade-{decade}", ShelfKind.DECADE, (("decade", decade),), tuple(items))
        )
    return shelves


def labels(index: BrowseIndex) -> Shelf:
    """The labels with the most releases in our data."""
    ranked = sorted(
        (lb for lb in index.labels.values() if lb.release_ids),
        key=lambda lb: (-len(lb.release_ids), lb.name.casefold(), lb.id),
    )[:CANDIDATES]
    items = [
        ShelfItem(
            _reason(
                ReasonKind.LABEL_RELEASES,
                count=len(lb.release_ids),
                artists=sum(1 for a in lb.artist_ids if a in index.graph.nodes),
            ),
            label_id=lb.id,
        )
        for lb in ranked
    ]
    return Shelf("labels", ShelfKind.LABELS, (), tuple(items))


def catalog_shelves(index: BrowseIndex) -> tuple[Shelf, ...]:
    """Every date-independent shelf, in display order (computed once per catalog version)."""
    return (
        behind_the_hits(index),
        super_connectors(index),
        genre_bridges(index),
        *genre_shelves(index),
        *decade_shelves(index),
        labels(index),
    )


def home_shelves(catalog: tuple[Shelf, ...], today: Shelf | None) -> tuple[Shelf, ...]:
    """Places the day's shelf after the first three catalog shelves."""
    if today is None:
        return catalog
    return (*catalog[:3], today, *catalog[3:])
