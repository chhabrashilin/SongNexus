"""Reads and writes artist photos (table ``artist_images``, ADR 0009)."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from songnexus.core.graph.model import ArtistImage
from songnexus.storage import models as m


@dataclass(frozen=True)
class ImageRecord:
    """One accepted image as stored: the URLs, the original size and the attribution."""

    wikidata_id: str
    commons_file: str
    thumbnail_url: str
    large_url: str
    width: int
    height: int
    page_url: str
    author: str | None
    license: str
    license_url: str | None
    attribution_required: bool


_RECORD_FIELDS = tuple(f.name for f in fields(ImageRecord))
_DELETE_BATCH = 500  # artist IDs per DELETE, well under SQLite's parameter limit


@dataclass(frozen=True)
class WriteStats:
    """What a write changed."""

    inserted: int
    updated: int
    unchanged: int
    deleted: int


def artist_ids_by_musicbrainz_id(session: Session) -> dict[str, str]:
    """Returns {MusicBrainz artist ID: canonical artist ID} for every mapped artist."""
    rows = session.execute(
        select(m.EntitySourceMapping.source_entity_id, m.EntitySourceMapping.entity_id).where(
            m.EntitySourceMapping.entity_type == "artist",
            m.EntitySourceMapping.source_id == "musicbrainz",
        )
    )
    return {mbid: artist_id for mbid, artist_id in rows.all()}  # noqa: C416 (Result has keys())


def detail_levels(session: Session) -> dict[str, str]:
    """Returns {artist ID: detail level}, to fetch for the best-known artists first."""
    rows = session.execute(select(m.Artist.id, m.Artist.detail_level)).all()
    return {artist_id: level for artist_id, level in rows}  # noqa: C416


def write_images(
    session: Session,
    images: Mapping[str, ImageRecord | None],
    now: datetime,
) -> WriteStats:
    """Makes ``artist_images`` match ``images`` for the artists it names.

    ``None`` means the artist has no acceptable image now, so a stored one is
    removed (its file was replaced or relicensed). Unchanged rows keep their
    ``fetched_at``, so a re-run with the same answers writes nothing and the
    read model's image stamp, and with it every ETag, stays the same.
    Artists not named are left as they are.
    """
    # One row per artist at most, so reading the whole table is cheap and avoids
    # an IN list longer than the database's parameter limit.
    existing = {
        row.artist_id: row
        for row in session.scalars(select(m.ArtistImage))
        if row.artist_id in images
    }
    inserted = updated = unchanged = 0
    stale = [artist_id for artist_id, record in images.items() if record is None]
    for artist_id, record in images.items():
        if record is None:
            continue
        values = {name: getattr(record, name) for name in _RECORD_FIELDS}
        row = existing.get(artist_id)
        if row is None:
            session.add(m.ArtistImage(artist_id=artist_id, fetched_at=now, **values))
            inserted += 1
        elif any(getattr(row, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(row, k, v)
            row.fetched_at = now
            updated += 1
        else:
            unchanged += 1
    removed = sorted(artist_id for artist_id in stale if artist_id in existing)
    for start in range(0, len(removed), _DELETE_BATCH):
        batch = removed[start : start + _DELETE_BATCH]
        session.execute(delete(m.ArtistImage).where(m.ArtistImage.artist_id.in_(batch)))
    return WriteStats(inserted, updated, unchanged, len(removed))


def read_artist_images(session: Session) -> dict[str, ArtistImage]:
    """Returns {artist ID: image} for every stored image (loaded once per read model)."""
    return {
        row.artist_id: ArtistImage(
            url=row.large_url,
            thumbnail_url=row.thumbnail_url,
            width=row.width,
            height=row.height,
            page_url=row.page_url,
            author=row.author,
            license=row.license,
            license_url=row.license_url,
        )
        for row in session.scalars(select(m.ArtistImage))
    }


def images_stamp(session: Session) -> str | None:
    """Returns a short fingerprint of the stored images, or None when there are none.

    It joins the catalog version, so a ``fetch-images`` run that changes rows
    reloads the read model and changes every cache key and ETag.
    """
    count, latest = session.execute(
        select(func.count(), func.max(m.ArtistImage.fetched_at)).select_from(m.ArtistImage)
    ).one()
    if not count:
        return None
    return hashlib.sha256(f"{count}|{latest}".encode()).hexdigest()[:8]
