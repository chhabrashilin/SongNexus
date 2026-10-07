"""Reads catalog facts from the database for the graph projection."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from songnexus.core.graph.model import SubjectType
from songnexus.core.graph.projection import (
    ArtistFact,
    CatalogFacts,
    CreditFact,
    GenreFact,
    LabelReleaseFact,
    RelationFact,
)
from songnexus.core.model import CreditRole, RelationType
from songnexus.storage import models as m


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and date[:4].isdigit() else None


def catalog_version(session: Session) -> str | None:
    """Returns the version of the catalog (the latest successful run), or None if empty."""
    run = session.scalars(
        select(m.IngestionRun)
        .where(m.IngestionRun.status == "succeeded")
        .order_by(m.IngestionRun.id.desc())
        .limit(1)
    ).first()
    return None if run is None else f"{run.pipeline_version}+run{run.id}"


def _artists(session: Session) -> Iterator[ArtistFact]:
    for row in session.execute(
        select(
            m.Artist.id,
            m.Artist.name,
            m.Artist.detail_level,
            m.Artist.artist_type,
            m.Artist.country,
            m.Artist.disambiguation,
            m.Artist.begin_date,
        )
    ):
        yield ArtistFact(*row)


def _genres(session: Session) -> Iterator[GenreFact]:
    stmt = select(m.ArtistGenre.artist_id, m.Genre.id, m.Genre.name, m.ArtistGenre.votes).join(
        m.Genre, m.Genre.id == m.ArtistGenre.genre_id
    )
    for row in session.execute(stmt):
        yield GenreFact(*row)


def _credits(session: Session) -> Iterator[CreditFact]:
    stmt = select(
        m.RecordingCredit.recording_id, m.RecordingCredit.artist_id, m.RecordingCredit.role
    )
    for recording_id, artist_id, role in session.execute(stmt):
        yield CreditFact(SubjectType.RECORDING, recording_id, artist_id, CreditRole(role))
    for release_id, artist_id in session.execute(
        select(m.ReleaseArtist.release_id, m.ReleaseArtist.artist_id)
    ):
        yield CreditFact(SubjectType.RELEASE, release_id, artist_id, CreditRole.PRIMARY)
    stmt = select(m.ReleaseCredit.release_id, m.ReleaseCredit.artist_id, m.ReleaseCredit.role)
    for release_id, artist_id, role in session.execute(stmt):
        yield CreditFact(SubjectType.RELEASE, release_id, artist_id, CreditRole(role))


def _relations(session: Session) -> Iterator[RelationFact]:
    stmt = select(
        m.ArtistRelation.id,
        m.ArtistRelation.subject_artist_id,
        m.ArtistRelation.object_artist_id,
        m.ArtistRelation.relation_type,
    )
    for relation_id, subject, obj, relation_type in session.execute(stmt):
        yield RelationFact(relation_id, subject, obj, RelationType(relation_type))


def _label_releases(session: Session) -> Iterator[LabelReleaseFact]:
    stmt = (
        select(
            m.ReleaseLabel.label_id,
            m.ReleaseLabel.release_id,
            m.ReleaseArtist.artist_id,
            m.Release.first_release_date,
        )
        .join(m.ReleaseArtist, m.ReleaseArtist.release_id == m.ReleaseLabel.release_id)
        .join(m.Release, m.Release.id == m.ReleaseLabel.release_id)
    )
    for label_id, release_id, artist_id, date in session.execute(stmt):
        yield LabelReleaseFact(label_id, release_id, artist_id, _year(date))


def read_catalog_facts(session: Session) -> CatalogFacts:
    """Loads every fact the projection needs (materialized; the session can close)."""
    titles: dict[str, str] = {}
    years: dict[str, int] = {}
    for model in (m.Recording, m.Release):
        for subject_id, title, date in session.execute(
            select(model.id, model.title, model.first_release_date)
        ):
            titles[subject_id] = title
            if (year := _year(date)) is not None:
                years[subject_id] = year
    for label_id, name in session.execute(select(m.Label.id, m.Label.name)):
        titles[label_id] = name
    return CatalogFacts(
        artists=list(_artists(session)),
        genres=list(_genres(session)),
        credits=list(_credits(session)),
        relations=list(_relations(session)),
        label_releases=list(_label_releases(session)),
        titles=titles,
        years=years,
    )


@dataclass(frozen=True)
class SearchEntry:
    """A searchable entity with what the index and its subtitle need.

    Attributes:
        entity_type: "artist", "release" or "recording".
        entity_id: Canonical ID.
        name: Display name.
        aliases: Other names (artists only).
        detail: Disambiguation (artists) or year (releases, recordings).
        artist_names: Primary artist names (releases and recordings).
        artist_ids: Primary artist IDs, in the same order.
        popularity: A raw popularity signal: credits for recordings, recordings
            for releases (artists use graph degree, computed by the caller).
    """

    entity_type: str
    entity_id: str
    name: str
    aliases: tuple[str, ...] = ()
    detail: str | None = None
    artist_names: tuple[str, ...] = ()
    artist_ids: tuple[str, ...] = ()
    popularity: int = 0


def read_search_entries(session: Session) -> list[SearchEntry]:
    """Loads every searchable entity, in a stable order."""
    aliases: dict[str, list[str]] = defaultdict(list)
    for artist_id, alias in session.execute(
        select(m.ArtistAlias.artist_id, m.ArtistAlias.alias).order_by(m.ArtistAlias.id)
    ):
        aliases[artist_id].append(alias)
    artist_names = dict(session.execute(select(m.Artist.id, m.Artist.name)).all())

    entries = [
        SearchEntry("artist", artist_id, name, tuple(aliases[artist_id]), disambiguation)
        for artist_id, name, disambiguation in session.execute(
            select(m.Artist.id, m.Artist.name, m.Artist.disambiguation).order_by(m.Artist.id)
        )
    ]

    release_artists: dict[str, list[str]] = defaultdict(list)
    for release_id, artist_id in session.execute(
        select(m.ReleaseArtist.release_id, m.ReleaseArtist.artist_id).order_by(
            m.ReleaseArtist.release_id, m.ReleaseArtist.position
        )
    ):
        release_artists[release_id].append(artist_id)
    release_sizes = dict(
        session.execute(
            select(m.ReleaseRecording.release_id, func.count()).group_by(
                m.ReleaseRecording.release_id
            )
        ).all()
    )
    for release_id, title, date in session.execute(
        select(m.Release.id, m.Release.title, m.Release.first_release_date).order_by(m.Release.id)
    ):
        entries.append(
            SearchEntry(
                "release",
                release_id,
                title,
                detail=date[:4] if date else None,
                artist_names=tuple(artist_names[a] for a in release_artists[release_id]),
                artist_ids=tuple(release_artists[release_id]),
                popularity=int(release_sizes.get(release_id, 0)),
            )
        )

    primaries: dict[str, list[str]] = defaultdict(list)
    credit_counts: dict[str, int] = defaultdict(int)
    for recording_id, artist_id, role in session.execute(
        select(
            m.RecordingCredit.recording_id, m.RecordingCredit.artist_id, m.RecordingCredit.role
        ).order_by(m.RecordingCredit.recording_id, m.RecordingCredit.id)
    ):
        credit_counts[recording_id] += 1
        if role == CreditRole.PRIMARY.value:
            primaries[recording_id].append(artist_id)
    for recording_id, title, date in session.execute(
        select(m.Recording.id, m.Recording.title, m.Recording.first_release_date).order_by(
            m.Recording.id
        )
    ):
        entries.append(
            SearchEntry(
                "recording",
                recording_id,
                title,
                detail=date[:4] if date else None,
                artist_names=tuple(artist_names[a] for a in primaries[recording_id]),
                artist_ids=tuple(primaries[recording_id]),
                popularity=credit_counts[recording_id],
            )
        )
    return entries


def canonical_ids_for_sources(session: Session, source_entity_ids: list[str]) -> dict[str, str]:
    """Maps source (MusicBrainz) IDs to canonical entity IDs via source mappings."""
    stmt = select(m.EntitySourceMapping.source_entity_id, m.EntitySourceMapping.entity_id).where(
        m.EntitySourceMapping.source_entity_id.in_(source_entity_ids)
    )
    return dict(session.execute(stmt).all())
