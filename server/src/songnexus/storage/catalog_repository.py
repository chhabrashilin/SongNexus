"""Catalog queries the API needs beyond the in-memory graph.

Details that are only shown on one screen (aliases, links, a recording's
credits) stay in the database rather than bloating the shared read model.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import func, select
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


@dataclass(frozen=True)
class GenreCount:
    """A genre and how many artists carry it."""

    id: str
    name: str
    artist_count: int


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


def genre_counts(session: Session) -> list[GenreCount]:
    """Returns every genre with its artist count, most common first."""
    stmt = (
        select(m.Genre.id, m.Genre.name, func.count(m.ArtistGenre.artist_id))
        .join(m.ArtistGenre, m.ArtistGenre.genre_id == m.Genre.id)
        .group_by(m.Genre.id, m.Genre.name)
    )
    counts = [GenreCount(gid, name, int(n)) for gid, name, n in session.execute(stmt)]
    counts.sort(key=lambda g: (-g.artist_count, g.name))
    return counts
