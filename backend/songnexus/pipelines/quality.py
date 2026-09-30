"""Data-quality checks: invariants the canonical database must always satisfy.

Run after every ingestion (``songnexus quality``) and in the test suite
against the sample snapshot. Each check counts violations; zero means pass.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, aliased

from songnexus.db import models as m

_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
MAX_TRACK_MS = 3 * 60 * 60 * 1000


@dataclass(frozen=True)
class QualityResult:
    name: str
    passed: bool
    violations: int
    description: str


def _count(session: Session, stmt: Select[Any]) -> int:
    return int(session.scalar(stmt) or 0)


def _orphans(model: type[m.Base], column: str, target: type[m.Base]) -> Callable[[Session], int]:
    def check(session: Session) -> int:
        target_alias = aliased(target)
        col = getattr(model, column)
        stmt = (
            select(func.count())
            .select_from(model)
            .outerjoin(target_alias, col == target_alias.id)  # type: ignore[attr-defined]
            .where(col.is_not(None), target_alias.id.is_(None))  # type: ignore[attr-defined]
        )
        return _count(session, stmt)

    return check


def _missing_provenance(model: type[m.Base]) -> Callable[[Session], int]:
    def check(session: Session) -> int:
        stmt = (
            select(func.count())
            .select_from(model)
            .where(
                or_(model.source_id.is_(None), model.raw_record_id.is_(None), model.ingestion_run_id.is_(None))  # type: ignore[attr-defined]
            )
        )
        return _count(session, stmt)

    return check


def _bad_confidence(model: type[m.Base]) -> Callable[[Session], int]:
    def check(session: Session) -> int:
        conf = model.confidence  # type: ignore[attr-defined]
        return _count(session, select(func.count()).select_from(model).where(or_(conf < 0, conf > 1)))

    return check


def _tracks_without_primary(session: Session) -> int:
    has_primary = select(m.TrackCredit.track_id).where(m.TrackCredit.role == "primary")
    return _count(session, select(func.count()).select_from(m.Track).where(m.Track.id.not_in(has_primary)))


def _entities_without_mapping(entity_type: str, model: type[m.Base]) -> Callable[[Session], int]:
    def check(session: Session) -> int:
        mapped = select(m.EntitySourceMapping.entity_id).where(m.EntitySourceMapping.entity_type == entity_type)
        return _count(session, select(func.count()).select_from(model).where(model.id.not_in(mapped)))  # type: ignore[attr-defined]

    return check


def _self_relationships(session: Session) -> int:
    rel = m.ArtistRelationship
    return _count(session, select(func.count()).select_from(rel).where(rel.source_artist_id == rel.target_artist_id))


def _albums_without_tracks(session: Session) -> int:
    with_tracks = select(m.AlbumTrack.album_id)
    return _count(session, select(func.count()).select_from(m.Album).where(m.Album.id.not_in(with_tracks)))


def _implausible_lengths(session: Session) -> int:
    length = m.Track.length_ms
    return _count(session, select(func.count()).select_from(m.Track).where(or_(length <= 0, length > MAX_TRACK_MS)))


def _malformed_dates(session: Session) -> int:
    values = [
        *session.scalars(select(m.Track.first_release_date).where(m.Track.first_release_date.is_not(None))),
        *session.scalars(select(m.Album.first_release_date).where(m.Album.first_release_date.is_not(None))),
        *session.scalars(select(m.Artist.begin_date).where(m.Artist.begin_date.is_not(None))),
    ]
    return sum(1 for v in values if not _DATE.match(v))


def _duplicate_hydrated_names(session: Session) -> int:
    stmt = (
        select(m.Artist.normalized_name)
        .where(m.Artist.hydrated.is_(True))
        .group_by(m.Artist.normalized_name)
        .having(func.count() > 1)
    )
    return len(session.execute(stmt).all())


CHECKS: list[tuple[str, str, Callable[[Session], int]]] = [
    (
        "credit_artist_exists",
        "every track credit references an existing artist",
        _orphans(m.TrackCredit, "artist_id", m.Artist),
    ),
    (
        "credit_track_exists",
        "every track credit references an existing track",
        _orphans(m.TrackCredit, "track_id", m.Track),
    ),
    (
        "relationship_source_exists",
        "relationship sources exist",
        _orphans(m.ArtistRelationship, "source_artist_id", m.Artist),
    ),
    (
        "relationship_target_exists",
        "relationship targets exist",
        _orphans(m.ArtistRelationship, "target_artist_id", m.Artist),
    ),
    ("no_self_relationships", "no artist is related to itself", _self_relationships),
    ("credit_provenance", "every track credit has source, raw record and run", _missing_provenance(m.TrackCredit)),
    (
        "relationship_provenance",
        "every relationship has source, raw record and run",
        _missing_provenance(m.ArtistRelationship),
    ),
    ("alias_provenance", "every alias has source, raw record and run", _missing_provenance(m.ArtistAlias)),
    ("credit_confidence_range", "credit confidence within [0, 1]", _bad_confidence(m.TrackCredit)),
    ("mapping_confidence_range", "mapping confidence within [0, 1]", _bad_confidence(m.EntitySourceMapping)),
    ("track_has_primary_artist", "every track has at least one primary artist", _tracks_without_primary),
    (
        "artist_has_source_mapping",
        "every artist maps to a source record",
        _entities_without_mapping("artist", m.Artist),
    ),
    ("track_has_source_mapping", "every track maps to a source record", _entities_without_mapping("track", m.Track)),
    ("album_has_source_mapping", "every album maps to a source record", _entities_without_mapping("album", m.Album)),
    ("album_has_tracks", "every album has at least one track", _albums_without_tracks),
    ("track_length_plausible", "track lengths are within (0, 3h]", _implausible_lengths),
    ("dates_well_formed", "dates are YYYY, YYYY-MM or YYYY-MM-DD", _malformed_dates),
    ("hydrated_names_unique", "no two fully loaded artists share a normalized name", _duplicate_hydrated_names),
]


def run_quality_checks(session: Session) -> list[QualityResult]:
    results = []
    for name, description, check in CHECKS:
        violations = check(session)
        results.append(QualityResult(name, violations == 0, violations, description))
    return results
