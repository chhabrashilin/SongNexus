"""Catalog queries the API needs beyond the in-memory graph.

Details that are only shown on one screen (aliases, links, a recording's
credits) stay in the database rather than bloating the shared read model.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from songnexus.storage import models as m

# Web pages for source entities, so every fact can be checked by a person.
_MUSICBRAINZ_PAGES = {
    "artist": "https://musicbrainz.org/artist/{}",
    "release": "https://musicbrainz.org/release-group/{}",
    "recording": "https://musicbrainz.org/recording/{}",
    "label": "https://musicbrainz.org/label/{}",
}


@dataclass(frozen=True)
class Alias:
    """An alternative artist name."""

    name: str
    alias_type: str
    locale: str | None


@dataclass(frozen=True)
class Link:
    """An external link."""

    link_type: str
    url: str


@dataclass(frozen=True)
class SourceRef:
    """Where a fact or entity comes from, as a page a person can open."""

    source: str
    source_id: str
    url: str


@dataclass(frozen=True)
class ArtistDetails:
    """What the artist page shows beyond the graph."""

    aliases: tuple[Alias, ...]
    links: tuple[Link, ...]
    sources: tuple[SourceRef, ...]


@dataclass(frozen=True)
class Credit:
    """An artist's credit on a recording."""

    artist_id: str
    role: str
    role_detail: str
    credited_as: str | None


@dataclass(frozen=True)
class Appearance:
    """Where a recording appears."""

    release_id: str
    title: str
    year: int | None
    disc_number: int
    position: int


@dataclass(frozen=True)
class RecordingDetails:
    """A recording with its credits and appearances."""

    id: str
    title: str
    length_ms: int | None
    first_release_date: str | None
    credits: tuple[Credit, ...]
    appearances: tuple[Appearance, ...]
    sources: tuple[SourceRef, ...]


def _sources(
    session: Session, entity_type: str, entity_ids: Iterable[str]
) -> dict[str, list[SourceRef]]:
    ids = list(entity_ids)
    found: dict[str, list[SourceRef]] = defaultdict(list)
    if not ids:
        return found
    stmt = (
        select(
            m.EntitySourceMapping.entity_id,
            m.EntitySourceMapping.source_id,
            m.EntitySourceMapping.source_entity_id,
        )
        .where(
            m.EntitySourceMapping.entity_type == entity_type,
            m.EntitySourceMapping.entity_id.in_(ids),
        )
        .order_by(m.EntitySourceMapping.confidence.desc(), m.EntitySourceMapping.source_entity_id)
    )
    page = _MUSICBRAINZ_PAGES[entity_type]
    for entity_id, source_id, source_entity_id in session.execute(stmt):
        found[entity_id].append(
            SourceRef(source_id, source_entity_id, page.format(source_entity_id))
        )
    return found


def artist_details(session: Session, artist_id: str) -> ArtistDetails:
    """Returns an artist's aliases, links and source records."""
    aliases = tuple(
        Alias(name, alias_type, locale)
        for name, alias_type, locale in session.execute(
            select(m.ArtistAlias.alias, m.ArtistAlias.alias_type, m.ArtistAlias.locale)
            .where(m.ArtistAlias.artist_id == artist_id)
            .order_by(m.ArtistAlias.alias_type, m.ArtistAlias.alias)
        )
    )
    links = tuple(
        Link(link_type, url)
        for link_type, url in session.execute(
            select(m.ArtistLink.link_type, m.ArtistLink.url)
            .where(m.ArtistLink.artist_id == artist_id)
            .order_by(m.ArtistLink.link_type, m.ArtistLink.url)
        )
    )
    sources = tuple(_sources(session, "artist", [artist_id]).get(artist_id, []))
    return ArtistDetails(aliases, links, sources)


def recording_details(session: Session, recording_id: str) -> RecordingDetails | None:
    """Returns a recording with credits and appearances, or None if unknown."""
    row = session.execute(
        select(
            m.Recording.id, m.Recording.title, m.Recording.length_ms, m.Recording.first_release_date
        ).where(m.Recording.id == recording_id)
    ).first()
    if row is None:
        return None
    credits = tuple(
        Credit(artist_id, role, role_detail, credited_as)
        for artist_id, role, role_detail, credited_as in session.execute(
            select(
                m.RecordingCredit.artist_id,
                m.RecordingCredit.role,
                m.RecordingCredit.role_detail,
                m.RecordingCredit.credited_as,
            )
            .where(m.RecordingCredit.recording_id == recording_id)
            .order_by(m.RecordingCredit.role, m.RecordingCredit.artist_id)
        )
    )
    appearances = tuple(
        Appearance(
            release_id,
            title,
            int(date[:4]) if date and date[:4].isdigit() else None,
            disc,
            position,
        )
        for release_id, title, date, disc, position in session.execute(
            select(
                m.Release.id,
                m.Release.title,
                m.Release.first_release_date,
                m.ReleaseRecording.disc_number,
                m.ReleaseRecording.position,
            )
            .join(m.ReleaseRecording, m.ReleaseRecording.release_id == m.Release.id)
            .where(m.ReleaseRecording.recording_id == recording_id)
            .order_by(m.Release.first_release_date, m.Release.id)
        )
    )
    sources = tuple(_sources(session, "recording", [recording_id]).get(recording_id, []))
    return RecordingDetails(row[0], row[1], row[2], row[3], credits, appearances, sources)


def subject_sources(
    session: Session, subjects: Iterable[tuple[str, str]]
) -> dict[str, list[SourceRef]]:
    """Returns source pages for evidence subjects, keyed by subject ID.

    Args:
        session: Database session.
        subjects: (subject type, subject ID) pairs; types are "recording",
            "release", "label" or "relation". A relation's source is the
            looked-up artist whose record asserted it.
    """
    by_type: dict[str, set[str]] = defaultdict(set)
    for subject_type, subject_id in subjects:
        by_type[subject_type].add(subject_id)
    found: dict[str, list[SourceRef]] = {}
    for entity_type in ("recording", "release", "label"):
        found.update(_sources(session, entity_type, by_type.get(entity_type, ())))
    relation_ids = by_type.get("relation", set())
    if relation_ids:
        asserted_by = dict(
            session.execute(
                select(m.ArtistRelation.id, m.RawRecord.request_key)
                .join(m.RawRecord, m.RawRecord.id == m.ArtistRelation.raw_record_id)
                .where(m.ArtistRelation.id.in_(relation_ids))
            ).all()
        )
        for relation_id, request_key in asserted_by.items():
            # Request keys look like "artist/<mbid>?inc=...".
            mbid = request_key.split("?", 1)[0].removeprefix("artist/")
            found[relation_id] = [
                SourceRef("musicbrainz", mbid, _MUSICBRAINZ_PAGES["artist"].format(mbid))
            ]
    return found


def _year_of(date: str | None) -> int | None:
    return int(date[:4]) if date and date[:4].isdigit() else None


@dataclass(frozen=True)
class LabelRelease:
    """A release on a label, with its primary artists."""

    release_id: str
    title: str
    year: int | None
    catalog_numbers: tuple[str, ...]
    artist_ids: tuple[str, ...]


@dataclass(frozen=True)
class LabelDetails:
    """What the label page shows: identity, releases in our data, and sources."""

    id: str
    name: str
    label_type: str | None
    disambiguation: str | None
    releases: tuple[LabelRelease, ...]
    sources: tuple[SourceRef, ...]


@dataclass(frozen=True)
class ArtistLabel:
    """A label an artist released on, with how many releases and when."""

    label_id: str
    name: str
    release_count: int
    first_year: int | None
    last_year: int | None


def label_details(session: Session, label_id: str) -> LabelDetails | None:
    """Returns a label with its releases (oldest first), or None if unknown."""
    row = session.execute(
        select(m.Label.id, m.Label.name, m.Label.label_type, m.Label.disambiguation).where(
            m.Label.id == label_id
        )
    ).first()
    if row is None:
        return None
    catalog_numbers: dict[str, set[str]] = defaultdict(set)
    releases: dict[str, tuple[str, str | None]] = {}
    for release_id, title, date, catalog_number in session.execute(
        select(
            m.Release.id,
            m.Release.title,
            m.Release.first_release_date,
            m.ReleaseLabel.catalog_number,
        )
        .join(m.ReleaseLabel, m.ReleaseLabel.release_id == m.Release.id)
        .where(m.ReleaseLabel.label_id == label_id)
    ):
        releases[release_id] = (title, date)
        if catalog_number:
            catalog_numbers[release_id].add(catalog_number)
    artists: dict[str, list[str]] = defaultdict(list)
    for release_id, artist_id in session.execute(
        select(m.ReleaseArtist.release_id, m.ReleaseArtist.artist_id)
        .where(m.ReleaseArtist.release_id.in_(list(releases)))
        .order_by(m.ReleaseArtist.release_id, m.ReleaseArtist.artist_id)
    ):
        artists[release_id].append(artist_id)
    items = sorted(
        (
            LabelRelease(
                release_id,
                title,
                _year_of(date),
                tuple(sorted(catalog_numbers[release_id])),
                tuple(artists[release_id]),
            )
            for release_id, (title, date) in releases.items()
        ),
        key=lambda r: (r.year is None, r.year or 0, r.title, r.release_id),
    )
    sources = tuple(_sources(session, "label", [label_id]).get(label_id, []))
    return LabelDetails(row.id, row.name, row.label_type, row.disambiguation, tuple(items), sources)


def artist_labels(session: Session, artist_id: str) -> list[ArtistLabel]:
    """Returns the labels an artist's releases came out on, most releases first."""
    by_label: dict[str, tuple[str, list[int | None]]] = {}
    for label_id, name, _release_id, date in session.execute(
        select(m.Label.id, m.Label.name, m.Release.id, m.Release.first_release_date)
        .join(m.ReleaseLabel, m.ReleaseLabel.label_id == m.Label.id)
        .join(m.Release, m.Release.id == m.ReleaseLabel.release_id)
        .join(m.ReleaseArtist, m.ReleaseArtist.release_id == m.Release.id)
        .where(m.ReleaseArtist.artist_id == artist_id)
        .distinct()
    ):
        by_label.setdefault(label_id, (name, []))[1].append(_year_of(date))
    labels = []
    for label_id, (name, years) in by_label.items():
        known = [y for y in years if y is not None]
        labels.append(
            ArtistLabel(
                label_id, name, len(years), min(known, default=None), max(known, default=None)
            )
        )
    labels.sort(key=lambda lb: (-lb.release_count, lb.name, lb.label_id))
    return labels


def recording_descriptors(session: Session, recording_id: str) -> dict[str, Any] | None:
    """Returns a recording's audio descriptor fields (AcousticBrainz), or None."""
    row = session.scalars(
        select(m.RecordingDescriptors).where(m.RecordingDescriptors.recording_id == recording_id)
    ).first()
    if row is None:
        return None
    return {
        "source_id": row.source_id,
        "source_recording_id": row.source_recording_id,
        "bpm": row.bpm,
        "key": row.key,
        "scale": row.scale,
        "key_strength": row.key_strength,
        "length_s": row.length_s,
        "average_loudness": row.average_loudness,
        "dynamic_complexity": row.dynamic_complexity,
        **(row.moods or {}),
    }


def descriptors_by_primary_artist(session: Session) -> list[tuple[str, str, dict[str, Any]]]:
    """Returns (recording ID, first primary artist ID, descriptor fields), for evaluation.

    Only recordings with descriptors and a primary artist are included.
    """
    primary: dict[str, str] = {}
    for recording_id, artist_id in session.execute(
        select(m.RecordingCredit.recording_id, m.RecordingCredit.artist_id)
        .where(m.RecordingCredit.role == "primary")
        .order_by(m.RecordingCredit.recording_id, m.RecordingCredit.artist_id)
    ):
        primary.setdefault(recording_id, artist_id)
    out = []
    for row in session.scalars(
        select(m.RecordingDescriptors).order_by(m.RecordingDescriptors.recording_id)
    ):
        if row.recording_id in primary:
            fields = {
                "bpm": row.bpm,
                "key": row.key,
                "scale": row.scale,
                "key_strength": row.key_strength,
                "length_s": row.length_s,
                "average_loudness": row.average_loudness,
                "dynamic_complexity": row.dynamic_complexity,
                **(row.moods or {}),
            }
            out.append((row.recording_id, primary[row.recording_id], fields))
    return out


@dataclass(frozen=True)
class Listening:
    """Aggregate listening for a set of artists: audiences and co-listening ranks."""

    audiences: dict[str, tuple[int, int]]  # artist -> (listeners, listens)
    ranks: dict[tuple[str, str], int]  # (artist, other) -> rank of other for artist


def audience_listeners(session: Session) -> dict[str, int]:
    """Returns {artist ID: public listener count} for every artist with audience data."""
    return {
        artist_id: listeners
        for artist_id, listeners in session.execute(
            select(m.ArtistAudience.artist_id, m.ArtistAudience.listeners)
        )
        if listeners is not None
    }


def listening(session: Session, artist_ids: list[str]) -> Listening:
    """Returns audiences of the artists and co-listening ranks among them."""
    audiences = {
        artist_id: (listeners, listens)
        for artist_id, listeners, listens in session.execute(
            select(
                m.ArtistAudience.artist_id, m.ArtistAudience.listeners, m.ArtistAudience.listens
            ).where(m.ArtistAudience.artist_id.in_(artist_ids))
        )
    }
    ranks = {
        (artist_id, other): rank
        for artist_id, other, rank in session.execute(
            select(
                m.ArtistCoListening.artist_id,
                m.ArtistCoListening.other_artist_id,
                m.ArtistCoListening.rank,
            ).where(
                m.ArtistCoListening.artist_id.in_(artist_ids),
                m.ArtistCoListening.other_artist_id.in_(artist_ids),
            )
        )
    }
    return Listening(audiences, ranks)


def colisteners(session: Session, artist_id: str, limit: int) -> list[tuple[str, int]]:
    """Returns (other artist, rank) for the artists most often played with ``artist_id``."""
    return [
        (other, rank)
        for other, rank in session.execute(
            select(m.ArtistCoListening.other_artist_id, m.ArtistCoListening.rank)
            .where(m.ArtistCoListening.artist_id == artist_id)
            .order_by(m.ArtistCoListening.rank)
            .limit(limit)
        )
    ]
