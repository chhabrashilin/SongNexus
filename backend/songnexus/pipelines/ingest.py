"""Stages 5-6: persist a canonical batch, recording the run and provenance.

Write semantics (see docs/data-pipeline.md):

* Entities (artists, albums, tracks, genres) are **upserted** by their
  deterministic IDs. They are never deleted by ingestion because another
  source may reference them.
* Facts (credits, relationships, aliases, ...) use **source-scoped sync**:
  after a run, the facts attributed to a source are exactly those in that
  source's snapshot. Stale facts are deleted, so the database is a pure
  function of its snapshots and re-ingestion is idempotent.
* The whole data write is one transaction. The run record is written in its
  own transactions so a failed run is still visible afterwards.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, delete, insert, select, tuple_, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from songnexus import PIPELINE_VERSION
from songnexus.db import models as m
from songnexus.db.session import session_scope
from songnexus.integrations.musicbrainz.snapshot import RawRecord, read_snapshot
from songnexus.pipelines.canonicalize import SOURCE_ID, CanonicalBatch, Row, build_batch

log = logging.getLogger(__name__)

CHUNK = 500

MUSICBRAINZ_SOURCE = {
    "id": SOURCE_ID,
    "name": "MusicBrainz",
    "homepage": "https://musicbrainz.org",
    "license": "CC0 1.0 (core data)",
}


def _chunks(rows: Sequence[Any], size: int = CHUNK) -> Iterable[Sequence[Any]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _pk_columns(model: type[m.Base]) -> list[Any]:
    return list(sa_inspect(model).primary_key)


def _pk_of(model: type[m.Base], row: Row) -> tuple[Any, ...]:
    return tuple(row[c.name] for c in _pk_columns(model))


def upsert(session: Session, model: type[m.Base], rows: Iterable[Row]) -> dict[str, int]:
    """Portable bulk upsert by primary key (works on SQLite and PostgreSQL)."""
    rows = list(rows)
    if not rows:
        return {"inserted": 0, "updated": 0}
    pk_cols = _pk_columns(model)
    existing: set[tuple[Any, ...]] = set()
    keys = [_pk_of(model, r) for r in rows]
    for chunk in _chunks(keys):
        stmt = select(*pk_cols).where(tuple_(*pk_cols).in_(chunk))
        existing.update(tuple(row) for row in session.execute(stmt))
    new_rows = [r for r, k in zip(rows, keys, strict=True) if k not in existing]
    old_rows = [r for r, k in zip(rows, keys, strict=True) if k in existing]
    for chunk in _chunks(new_rows):
        session.execute(insert(model), list(chunk))
    for chunk in _chunks(old_rows):
        session.execute(update(model), list(chunk))
    return {"inserted": len(new_rows), "updated": len(old_rows)}


def sync_source_facts(session: Session, model: type[m.Base], rows: Iterable[Row], source_id: str) -> dict[str, int]:
    """Make the facts attributed to ``source_id`` exactly equal to ``rows``."""
    rows = list(rows)
    pk_cols = _pk_columns(model)
    wanted = {_pk_of(model, r) for r in rows}
    current = {
        tuple(r)
        for r in session.execute(select(*pk_cols).where(model.source_id == source_id))  # type: ignore[attr-defined]
    }
    stale = sorted(current - wanted)
    for chunk in _chunks(stale):
        session.execute(delete(model).where(tuple_(*pk_cols).in_(chunk)))
    counts = upsert(session, model, rows)
    counts["deleted"] = len(stale)
    return counts


def _attach_provenance(rows: Iterable[Row], raw_ids: dict[str, int], run_id: int) -> list[Row]:
    attached = []
    for row in rows:
        out = {k: v for k, v in row.items() if k != "_raw_key"}
        out["raw_record_id"] = raw_ids[row["_raw_key"]]
        out["ingestion_run_id"] = run_id
        attached.append(out)
    return attached


def _with_run(rows: Iterable[Row], run_id: int) -> list[Row]:
    return [{**row, "ingestion_run_id": run_id} for row in rows]


def _write_raw_records(session: Session, records: list[RawRecord], run_id: int) -> dict[str, int]:
    rows = [
        {
            "source_id": SOURCE_ID,
            "kind": r.kind,
            "request_key": r.request_key,
            "url": r.url,
            "retrieved_at": r.retrieved_at,
            "content_hash": r.content_hash,
            "payload": r.body,
            "last_seen_run_id": run_id,
        }
        for r in records
    ]
    existing = dict(
        session.execute(select(m.RawRecord.request_key, m.RawRecord.id).where(m.RawRecord.source_id == SOURCE_ID)).all()
    )
    new_rows = [r for r in rows if r["request_key"] not in existing]
    for chunk in _chunks(new_rows):
        session.execute(insert(m.RawRecord), list(chunk))
    updates = [{**r, "id": existing[r["request_key"]]} for r in rows if r["request_key"] in existing]
    for chunk in _chunks(updates):
        session.execute(update(m.RawRecord), list(chunk))
    return dict(
        session.execute(select(m.RawRecord.request_key, m.RawRecord.id).where(m.RawRecord.source_id == SOURCE_ID)).all()
    )


def write_batch(session: Session, batch: CanonicalBatch, records: list[RawRecord], run_id: int) -> dict[str, Any]:
    raw_ids = _write_raw_records(session, records, run_id)
    counts: dict[str, Any] = {}

    # Entities before facts so that fact foreign keys always resolve.
    counts["artists"] = upsert(session, m.Artist, _with_run(batch.artists.values(), run_id))
    counts["genres"] = upsert(session, m.Genre, batch.genres.values())
    counts["albums"] = upsert(session, m.Album, _with_run(batch.albums.values(), run_id))
    counts["tracks"] = upsert(session, m.Track, _with_run(batch.tracks.values(), run_id))

    fact_tables: list[tuple[str, type[m.Base], Iterable[Row]]] = [
        ("artist_aliases", m.ArtistAlias, batch.aliases.values()),
        ("artist_links", m.ArtistLink, batch.links.values()),
        ("artist_genres", m.ArtistGenre, batch.artist_genres.values()),
        ("album_artists", m.AlbumArtist, batch.album_artists.values()),
        ("album_tracks", m.AlbumTrack, batch.album_tracks.values()),
        ("album_credits", m.AlbumCredit, batch.album_credits.values()),
        ("track_credits", m.TrackCredit, batch.track_credits.values()),
        ("artist_relationships", m.ArtistRelationship, batch.artist_relationships.values()),
    ]
    for name, model, rows in fact_tables:
        counts[name] = sync_source_facts(session, model, _attach_provenance(rows, raw_ids, run_id), SOURCE_ID)
    counts["entity_source_mappings"] = sync_source_facts(
        session, m.EntitySourceMapping, _with_run(batch.mappings.values(), run_id), SOURCE_ID
    )
    return counts


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ingest_snapshot(engine: Engine, snapshot_path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    with session_scope(engine) as session:
        upsert(session, m.DataSource, [MUSICBRAINZ_SOURCE])
        run = m.IngestionRun(
            source_id=SOURCE_ID,
            pipeline_version=PIPELINE_VERSION,
            snapshot_sha256=_file_sha256(snapshot_path),
            started_at=datetime.now(UTC),
            status="running",
            stats={},
        )
        session.add(run)
        session.flush()
        run_id = run.id

    try:
        records = list(read_snapshot(snapshot_path))
        batch = build_batch(records)
        with session_scope(engine) as session:
            counts = write_batch(session, batch, records, run_id)
            elapsed = time.perf_counter() - started
            stats: dict[str, Any] = {
                "run_id": run_id,
                "pipeline_version": PIPELINE_VERSION,
                "records": len(records),
                "records_per_second": round(len(records) / elapsed, 1) if elapsed else None,
                "elapsed_s": round(elapsed, 2),
                "batch": dict(batch.stats),
                "rejected": batch.rejected,
                "ignored_relation_types": dict(batch.ignored_relation_types.most_common()),
                "writes": counts,
            }
            session.execute(
                update(m.IngestionRun)
                .where(m.IngestionRun.id == run_id)
                .values(status="succeeded", finished_at=datetime.now(UTC), stats=stats)
            )
    except Exception as exc:
        with session_scope(engine) as session:
            session.execute(
                update(m.IngestionRun)
                .where(m.IngestionRun.id == run_id)
                .values(status="failed", finished_at=datetime.now(UTC), error=repr(exc)[:2000])
            )
        log.exception("ingestion failed", extra={"run_id": run_id})
        raise
    log.info("ingestion succeeded", extra={"run_id": run_id, "elapsed_s": stats["elapsed_s"]})
    return stats
