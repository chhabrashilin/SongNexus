"""The browse index: per-catalog-version facts behind shelves, genre pages and recommendations.

Pure and deterministic. The storage layer reads plain facts (``BrowseFacts``:
recordings with their dates and credits, labels, aggregate co-listening), and
``build_index`` joins them with the artist graph once per catalog version. Every
number a browse surface shows (credited recordings, collaborators, genres
bridged) is a count over these facts, so the client can print it and the viewer
can check it.

Definitions used throughout:

- **Collaborators**: an artist's distinct neighbors under the default connection
  kinds (everything except label mates and engineering), as on artist pages.
- **Top-level genre**: a genre with no parent in the served hierarchy. An
  artist's *primary* top-level genre is the one its genre shares add up to most
  (each genre counts toward every top-level genre above it).
- **In a genre**: an artist with at least ``DEFAULT_MIN_GENRE_SHARE`` of its genre
  shares in the genre (or its subgenres), the same rule as the genre filter.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from songnexus.core.graph.algorithms import weighted_degree
from songnexus.core.graph.filters import DEFAULT_MIN_GENRE_SHARE
from songnexus.core.graph.model import (
    DEFAULT_CATEGORIES,
    ArtistGraph,
    EdgeKind,
    GenreShare,
    SubjectType,
    kinds_for,
)
from songnexus.core.model import PERFORMER_ROLES, CreditRole

DEFAULT_KINDS = kinds_for(DEFAULT_CATEGORIES)
_PERFORMER_NAMES = frozenset(r.value for r in PERFORMER_ROLES)
_FULL_DATE = len("YYYY-MM-DD")


@dataclass(frozen=True)
class RecordingFact:
    """A recording: its title, first release date and every credit on it.

    Attributes:
        id: Canonical recording ID.
        title: Its title.
        date: First release date (``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD``), when known.
        credits: (artist ID, role) pairs, roles from ``CreditRole``.
    """

    id: str
    title: str
    date: str | None = None
    credits: tuple[tuple[str, str], ...] = ()

    @property
    def year(self) -> int | None:
        """The release year, when the date has one."""
        return int(self.date[:4]) if self.date and self.date[:4].isdigit() else None

    @property
    def month_day(self) -> str | None:
        """``MM-DD`` when the date is a full day, else None."""
        date = self.date
        if date and len(date) >= _FULL_DATE and date[4] == "-" and date[7] == "-":
            return date[5:_FULL_DATE]
        return None


@dataclass(frozen=True)
class LabelFact:
    """A label, its releases in our data and those releases' primary artists."""

    id: str
    name: str
    release_ids: frozenset[str] = frozenset()
    artist_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class BrowseFacts:
    """Everything the browse index reads besides the graph.

    Attributes:
        recordings: Every recording with its credits.
        release_tracks: Release ID -> its recordings in track order.
        release_artists: Release ID -> its primary artists.
        labels: Every label with releases.
        colistening: Artist -> (other artist, rank) pairs from aggregate listening
            data: the artists most often played in the same sessions (1 = most).
        listeners: Artist -> listener count from the same aggregate data.
    """

    recordings: Sequence[RecordingFact] = ()
    release_tracks: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    release_artists: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    labels: Sequence[LabelFact] = ()
    colistening: Mapping[str, Sequence[tuple[str, int]]] = field(default_factory=dict)
    listeners: Mapping[str, int] = field(default_factory=dict)


def decade_of(year: int) -> int:
    """Returns the decade a year belongs to (1994 -> 1990)."""
    return year - year % 10


class BrowseIndex:
    """Derived views of one catalog version, built once and shared read-only."""

    def __init__(self, graph: ArtistGraph, facts: BrowseFacts) -> None:
        """Joins the graph with the browse facts (O(credits + artists + edges))."""
        self.graph = graph
        adjacency = graph.adjacency(DEFAULT_KINDS)
        self.adjacency = adjacency
        self.degree: dict[str, int] = {a: len(n) for a, n in adjacency.items()}
        self.strength: dict[str, float] = weighted_degree(adjacency)
        self.recordings: dict[str, RecordingFact] = {r.id: r for r in facts.recordings}
        self.release_tracks = dict(facts.release_tracks)
        self.labels: dict[str, LabelFact] = {lb.id: lb for lb in facts.labels}
        self.listeners = dict(facts.listeners)
        self.colistening: dict[str, dict[str, int]] = {
            a: {o: r for o, r in rows if o in graph.nodes}
            for a, rows in facts.colistening.items()
            if a in graph.nodes
        }
        # The reverse view: artist -> {who lists them: the rank they hold there}.
        listed_by: dict[str, dict[str, int]] = defaultdict(dict)
        for artist_id, rows in self.colistening.items():
            for other, rank in rows.items():
                listed_by[other][artist_id] = rank
        self.colistened_by: dict[str, dict[str, int]] = dict(listed_by)
        self._index_credits(facts)
        artist_labels: dict[str, list[str]] = defaultdict(list)
        for label in sorted(facts.labels, key=lambda lb: lb.id):
            for artist_id in sorted(label.artist_ids):
                if artist_id in graph.nodes:
                    artist_labels[artist_id].append(label.id)
        self.artist_labels: dict[str, list[str]] = dict(artist_labels)
        self.genre_roots = _genre_roots(graph)
        self.primary_root = self._primary_roots()

    def _index_credits(self, facts: BrowseFacts) -> None:
        """Indexes recordings by artist and role, by month-day, and their primary artists."""
        graph = self.graph
        # Built with defaultdicts, stored as plain dicts: readers share the index
        # across threads, and a defaultdict read of a missing key would write.
        by_role: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        by_month_day: dict[str, list[str]] = defaultdict(list)
        self.primary_artists: dict[str, tuple[str, ...]] = {}
        for recording in facts.recordings:
            primaries = []
            for artist_id, role in recording.credits:
                if artist_id not in graph.nodes:
                    continue
                by_role[artist_id][role].add(recording.id)
                if role == CreditRole.PRIMARY.value and artist_id not in primaries:
                    primaries.append(artist_id)
            self.primary_artists[recording.id] = tuple(
                sorted(primaries, key=lambda a: (graph.nodes[a].name, a))
            )
            if (day := recording.month_day) is not None and primaries:
                by_month_day[day].append(recording.id)
        self.recordings_by_role: dict[str, dict[str, set[str]]] = {
            a: dict(roles) for a, roles in by_role.items()
        }
        self.by_month_day: dict[str, list[str]] = dict(by_month_day)

        self.performers: frozenset[str] = frozenset(
            a
            for a, roles in self.recordings_by_role.items()
            if any(roles.get(r) for r in _PERFORMER_NAMES)
        ) | frozenset(
            a for artists in facts.release_artists.values() for a in artists if a in graph.nodes
        )

    def _primary_roots(self) -> dict[str, str]:
        """Artist -> the top-level genre its genre shares add up to most (ties: bigger genre)."""
        graph = self.graph
        counts = graph.genre_artist_counts()
        primary: dict[str, str] = {}
        for node in graph.nodes.values():
            scores: dict[str, float] = defaultdict(float)
            for share in node.genres:
                for root in self.genre_roots.get(share.genre_id, ()):
                    scores[root] += share.share
            if scores:
                primary[node.id] = min(
                    scores,
                    key=lambda r: (-scores[r], -counts.get(r, (0, 0))[1], graph.genre_names[r], r),
                )
        return primary

    def connectedness_key(self, artist_id: str) -> tuple[int, float, str, str]:
        """Sort key: most collaborators first, then strongest, then by name."""
        return (
            -self.degree.get(artist_id, 0),
            -self.strength.get(artist_id, 0.0),
            self.graph.nodes[artist_id].name,
            artist_id,
        )

    def top_level_genres(self) -> list[str]:
        """Top-level genres with artists, most artists (with subgenres) first."""
        counts = self.graph.genre_artist_counts()
        roots = {r for roots in self.genre_roots.values() for r in roots}
        return sorted(
            (r for r in roots if r in counts and not self.graph.genre_parents.get(r)),
            key=lambda r: (-counts[r][1], self.graph.genre_names[r], r),
        )

    def genre_artists(self, genre_id: str, *, include_subgenres: bool = True) -> list[str]:
        """Artists in a genre (by the genre-filter rule), most connected first."""
        genres = (
            self.graph.with_subgenres([genre_id]) if include_subgenres else frozenset([genre_id])
        )
        members = [
            node.id
            for node in self.graph.nodes.values()
            if genre_share(node.genres, genres) >= DEFAULT_MIN_GENRE_SHARE
        ]
        members.sort(key=self.connectedness_key)
        return members

    def decades(self, artist_id: str, roles: Iterable[str] | None = None) -> Counter[int]:
        """Counts an artist's distinct dated recordings per decade (optionally by role)."""
        by_role = self.recordings_by_role.get(artist_id, {})
        wanted = by_role.keys() if roles is None else roles
        recording_ids = set().union(*(by_role.get(r, set()) for r in wanted))
        counts: Counter[int] = Counter()
        for recording_id in recording_ids:
            year = self.recordings[recording_id].year
            if year is not None:
                counts[decade_of(year)] += 1
        return counts


def genre_share(genres: Iterable[GenreShare], genre_ids: frozenset[str]) -> float:
    """Returns the summed share of ``genres`` that falls in ``genre_ids``."""
    return sum(g.share for g in genres if g.genre_id in genre_ids)


def _genre_roots(graph: ArtistGraph) -> dict[str, frozenset[str]]:
    """Maps every genre to its top-level ancestors (itself when it has no parent).

    The hierarchy is community data and may contain cycles; a genre whose every
    ancestor has a parent (a pure cycle) is treated as its own root.
    """
    roots: dict[str, frozenset[str]] = {}
    for genre_id in set(graph.genre_names) | set(graph.genre_parents):
        seen = {genre_id}
        frontier = [genre_id]
        found: set[str] = set()
        while frontier:
            current = frontier.pop()
            parents = graph.genre_parents.get(current, frozenset())
            if not parents:
                found.add(current)
            for parent in parents:
                if parent not in seen:
                    seen.add(parent)
                    frontier.append(parent)
        roots[genre_id] = frozenset(found or {genre_id})
    return roots


def build_index(graph: ArtistGraph, facts: BrowseFacts) -> BrowseIndex:
    """Builds the browse index for one catalog version."""
    return BrowseIndex(graph, facts)


def adamic_adar_weight(degree: int) -> float:
    """The weight of one shared collaborator: rarer (lower-degree) links count more.

    The Adamic-Adar link-prediction score: a collaborator who works with
    everybody says less about two artists than one who works with few.
    """
    return 1.0 / math.log(max(degree, 2))


@dataclass(frozen=True)
class TrackPick:
    """A real recording that stands for one step of a path.

    Attributes:
        recording_id: The recording.
        release_id: Set when the step's credit is on this release rather than
            the recording itself (the recording is the release's first track).
    """

    recording_id: str
    release_id: str | None = None


_KIND_ORDER = {kind: i for i, kind in enumerate(EdgeKind)}


def step_track(
    index: BrowseIndex,
    u: str,
    v: str,
    kinds: frozenset[EdgeKind],
    *,
    avoid: frozenset[str] = frozenset(),
) -> TrackPick | None:
    """Picks one recording that proves the step u-v, for a playlist made from a path.

    Prefers recordings both artists are credited on, with one of them as the
    primary artist, in the order evidence is explained (performances first,
    then by title); recordings in ``avoid`` (already on the playlist) only when
    nothing else exists. Falls back to the first track of a release both are
    credited on. Steps proven only by a relation (band membership) have no track.
    """
    edge = index.graph.edge(u, v)
    if edge is None:
        return None
    direct: list[tuple[tuple[int, int, int, str, str], TrackPick]] = []
    for evidence in edge.evidence:
        if evidence.kind not in kinds:
            continue
        if evidence.subject_type is SubjectType.RECORDING:
            recording_id = evidence.subject_id
            release_id = None
        elif evidence.subject_type is SubjectType.RELEASE:
            tracks = index.release_tracks.get(evidence.subject_id, ())
            if not tracks:
                continue
            recording_id, release_id = tracks[0], evidence.subject_id
        else:
            continue
        recording = index.recordings.get(recording_id)
        if recording is None:
            continue
        led_by_step = bool({u, v} & set(index.primary_artists.get(recording_id, ())))
        key = (
            int(recording_id in avoid),
            int(release_id is not None),
            int(not led_by_step),
            f"{_KIND_ORDER[evidence.kind]:02d}{recording.title.casefold()}",
            recording_id,
        )
        direct.append((key, TrackPick(recording_id, release_id)))
    if not direct:
        return None
    return min(direct, key=lambda item: item[0])[1]
