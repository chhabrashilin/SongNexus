"""SQL access for catalog entities and their provenance. No business logic here."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from songnexus.db import models as m

SOURCE_ENTITY_URLS = {
    ("musicbrainz", "artist"): "https://musicbrainz.org/artist/{}",
    ("musicbrainz", "track"): "https://musicbrainz.org/recording/{}",
    ("musicbrainz", "album"): "https://musicbrainz.org/release-group/{}",
}


def source_url(source_id: str, entity_type: str, source_entity_id: str) -> str | None:
    template = SOURCE_ENTITY_URLS.get((source_id, entity_type))
    return template.format(source_entity_id) if template else None


class CatalogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def artist(self, artist_id: str) -> m.Artist | None:
        return self.session.get(m.Artist, artist_id)

    def artist_genres(self, artist_id: str) -> list[tuple[str, int]]:
        rows = self.session.execute(
            select(m.Genre.name, m.ArtistGenre.votes)
            .join(m.Genre)
            .where(m.ArtistGenre.artist_id == artist_id)
            .order_by(m.ArtistGenre.votes.desc(), m.Genre.name)
        )
        return [(name, votes) for name, votes in rows]

    def artist_aliases(self, artist_id: str) -> Sequence[m.ArtistAlias]:
        return self.session.scalars(
            select(m.ArtistAlias).where(m.ArtistAlias.artist_id == artist_id).order_by(m.ArtistAlias.alias)
        ).all()

    def artist_links(self, artist_id: str) -> Sequence[m.ArtistLink]:
        return self.session.scalars(
            select(m.ArtistLink)
            .where(m.ArtistLink.artist_id == artist_id)
            .order_by(m.ArtistLink.link_type, m.ArtistLink.url)
        ).all()

    def artist_albums(self, artist_id: str) -> Sequence[m.Album]:
        return self.session.scalars(
            select(m.Album)
            .join(m.AlbumArtist, m.AlbumArtist.album_id == m.Album.id)
            .where(m.AlbumArtist.artist_id == artist_id)
            .order_by(m.Album.first_release_date, m.Album.title)
        ).all()

    def track(self, track_id: str) -> m.Track | None:
        return self.session.get(m.Track, track_id)

    def track_albums(self, track_id: str) -> Sequence[m.Album]:
        return self.session.scalars(
            select(m.Album)
            .join(m.AlbumTrack, m.AlbumTrack.album_id == m.Album.id)
            .where(m.AlbumTrack.track_id == track_id)
            .distinct()
            .order_by(m.Album.first_release_date)
        ).all()

    def track_credits(self, track_id: str) -> list[tuple[m.TrackCredit, str]]:
        rows = self.session.execute(
            select(m.TrackCredit, m.Artist.name)
            .join(m.Artist, m.Artist.id == m.TrackCredit.artist_id)
            .where(m.TrackCredit.track_id == track_id)
            .order_by(m.TrackCredit.role, m.Artist.name)
        )
        return [(credit, name) for credit, name in rows]

    def mappings(self, entity_type: str, entity_id: str) -> Sequence[m.EntitySourceMapping]:
        return self.session.scalars(
            select(m.EntitySourceMapping)
            .where(m.EntitySourceMapping.entity_type == entity_type, m.EntitySourceMapping.entity_id == entity_id)
            .order_by(m.EntitySourceMapping.confidence.desc(), m.EntitySourceMapping.source_entity_id)
        ).all()

    # -- provenance of facts --------------------------------------------------

    def track_credit_facts(self, track_id: str, artist_ids: Sequence[str]) -> Sequence[m.TrackCredit]:
        return self.session.scalars(
            select(m.TrackCredit)
            .where(m.TrackCredit.track_id == track_id, m.TrackCredit.artist_id.in_(artist_ids))
            .order_by(m.TrackCredit.artist_id, m.TrackCredit.role)
        ).all()

    def album_credit_facts(self, album_id: str, artist_ids: Sequence[str]) -> list[Any]:
        album_artists = self.session.scalars(
            select(m.AlbumArtist).where(m.AlbumArtist.album_id == album_id, m.AlbumArtist.artist_id.in_(artist_ids))
        ).all()
        credits = self.session.scalars(
            select(m.AlbumCredit).where(m.AlbumCredit.album_id == album_id, m.AlbumCredit.artist_id.in_(artist_ids))
        ).all()
        return [*album_artists, *credits]

    def relationship(self, rel_id: str) -> m.ArtistRelationship | None:
        return self.session.get(m.ArtistRelationship, rel_id)

    def raw_record(self, raw_record_id: int | None) -> m.RawRecord | None:
        return self.session.get(m.RawRecord, raw_record_id) if raw_record_id is not None else None

    def run(self, run_id: int) -> m.IngestionRun | None:
        return self.session.get(m.IngestionRun, run_id)

    def source(self, source_id: str) -> m.DataSource | None:
        return self.session.get(m.DataSource, source_id)
