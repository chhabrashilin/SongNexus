"""Persist a canonical batch, recording the run and provenance.

Write semantics:

* Facts (credits, relations, aliases, links, genre and label associations) and
  entity source mappings use source-scoped sync: after a run, the facts
  attributed to a source are exactly those in that source's snapshot. Stale facts
  are deleted, so the database is a pure function of its snapshots and
  re-ingestion is idempotent.
* Entities are upserted by their deterministic IDs. An entity no source maps to
  any more (and a genre no artist carries) is garbage-collected after the sync.
* The whole data write is one transaction, and the quality gate runs inside it:
  a catalog that fails the gate is rolled back and never served. The run record
  is written in its own transactions, so a failed run is still visible afterwards.
* On PostgreSQL a transaction-scoped advisory lock serializes concurrent ingests.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, delete, insert, select, text, tuple_, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from songnexus.catalog import PIPELINE_VERSION
from songnexus.catalog.canonicalize import (
    SOURCE_ID,
    SUPPLEMENTARY_SOURCE_ID,
    CanonicalBatch,
    Row,
    build_batch,
)
from songnexus.catalog.musicbrainz.snapshot import RawRecord, read_snapshot
from songnexus.catalog.quality import Severity, gate_passes, run_quality_checks
from songnexus.storage import models as m
from songnexus.storage.db import session_scope

log = logging.getLogger(__name__)

ADAPTER = "musicbrainz"
CHUNK = 500
# Arbitrary, stable key for pg_advisory_xact_lock ("songnexus ingest").
_INGEST_LOCK_KEY = 0x5309_1A6E


class QualityGateError(RuntimeError):
    """The new catalog violates an error-severity invariant; nothing was written."""


DATA_SOURCES: tuple[Row, ...] = (
    {
        "id": SOURCE_ID,
        "name": "MusicBrainz",
        "homepage": "https://musicbrainz.org",
        "license": "CC0-1.0",
    },
    {
        "id": SUPPLEMENTARY_SOURCE_ID,
        "name": "MusicBrainz (genres)",
        "homepage": "https://musicbrainz.org/doc/About/Data_License",
        "license": "CC-BY-NC-SA-3.0",
    },
)
_ADAPTER_SOURCES = tuple(s["id"] for s in DATA_SOURCES)


def _chunks(rows: Sequence[Any], size: int = CHUNK) -> Iterable[Sequence[Any]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _pk_columns(model: type[m.Base]) -> list[Any]:
    return list(sa_inspect(model).primary_key)


def _pk_of(model: type[m.Base], row: Row) -> tuple[Any, ...]:
    return tuple(row[c.name] for c in _pk_columns(model))


def upsert(session: Session, model: type[m.Base], rows: Iterable[Row]) -> dict[str, int]:
    """Inserts or updates rows by primary key, portably (SQLite and PostgreSQL).

    Rows are written in primary-key order so runs are deterministic.
    """
    ordered = sorted(rows, key=lambda r: _pk_of(model, r))
    if not ordered:
        return {"inserted": 0, "updated": 0}
    pk_cols = _pk_columns(model)
    keys = [_pk_of(model, r) for r in ordered]
    existing: set[tuple[Any, ...]] = set()
    for chunk in _chunks(keys):
        stmt = select(*pk_cols).where(tuple_(*pk_cols).in_(chunk))
        existing.update(tuple(row) for row in session.execute(stmt))
    new_rows = [r for r, k in zip(ordered, keys, strict=True) if k not in existing]
    old_rows = [r for r, k in zip(ordered, keys, strict=True) if k in existing]
    for chunk in _chunks(new_rows):
        session.execute(insert(model), list(chunk))
    for chunk in _chunks(old_rows):
        session.execute(update(model), list(chunk))
    return {"inserted": len(new_rows), "updated": len(old_rows)}


def sync_source_facts(
    session: Session, model: type[m.Base], rows: Iterable[Row], source_ids: Sequence[str]
) -> dict[str, int]:
    """Makes the rows attributed to ``source_ids`` exactly equal to ``rows``."""
    rows = list(rows)
    pk_cols = _pk_columns(model)
    wanted = {_pk_of(model, r) for r in rows}
    source_column = model.source_id  # type: ignore[attr-defined]
    current = {
        tuple(r) for r in session.execute(select(*pk_cols).where(source_column.in_(source_ids)))
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
    """Upserts raw records by request key and returns request key -> row ID."""

    def current_ids() -> dict[str, int]:
        stmt = select(m.RawRecord.request_key, m.RawRecord.id).where(
            m.RawRecord.source_id == SOURCE_ID
        )
        return dict(session.execute(stmt).all())

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
        for r in sorted(records, key=lambda r: r.request_key)
    ]
    existing = current_ids()
    new_rows = [r for r in rows if r["request_key"] not in existing]
    for chunk in _chunks(new_rows):
        session.execute(insert(m.RawRecord), list(chunk))
    updates = [
        {**r, "id": existing[r["request_key"]]} for r in rows if r["request_key"] in existing
    ]
    for chunk in _chunks(updates):
        session.execute(update(m.RawRecord), list(chunk))
    return current_ids()


def _collect_garbage(session: Session) -> dict[str, int]:
    """Deletes entities nothing maps to, and genres no artist carries."""
    deleted: dict[str, int] = {}
    for entity_type, model in m.ENTITY_MODELS.items():
        mapped = select(m.EntitySourceMapping.entity_id).where(
            m.EntitySourceMapping.entity_type == entity_type
        )
        entity_id = model.id  # type: ignore[attr-defined]
        result = session.execute(delete(model).where(entity_id.not_in(mapped)))
        deleted[entity_type] = int(result.rowcount)  # type: ignore[attr-defined]
    carried = select(m.ArtistGenre.genre_id)
    result = session.execute(delete(m.Genre).where(m.Genre.id.not_in(carried)))
    deleted["genre"] = int(result.rowcount)  # type: ignore[attr-defined]
    return deleted


def write_batch(
    session: Session, batch: CanonicalBatch, records: list[RawRecord], run_id: int
) -> dict[str, Any]:
    """Writes a batch in dependency order and returns per-table write counts."""
    raw_ids = _write_raw_records(session, records, run_id)
    counts: dict[str, Any] = {}

    # Entities before facts, so fact foreign keys always resolve.
    counts["artists"] = upsert(session, m.Artist, _with_run(batch.artists.values(), run_id))
    counts["genres"] = upsert(session, m.Genre, batch.genres.values())
    counts["labels"] = upsert(session, m.Label, _with_run(batch.labels.values(), run_id))
    counts["releases"] = upsert(session, m.Release, _with_run(batch.releases.values(), run_id))
    counts["recordings"] = upsert(
        session, m.Recording, _with_run(batch.recordings.values(), run_id)
    )

    fact_tables: list[tuple[str, type[m.Base], Iterable[Row]]] = [
        ("artist_aliases", m.ArtistAlias, batch.aliases.values()),
        ("artist_links", m.ArtistLink, batch.links.values()),
        ("artist_genres", m.ArtistGenre, batch.artist_genres.values()),
        ("release_artists", m.ReleaseArtist, batch.release_artists.values()),
        ("release_recordings", m.ReleaseRecording, batch.release_recordings.values()),
        ("release_labels", m.ReleaseLabel, batch.release_labels.values()),
        ("release_credits", m.ReleaseCredit, batch.release_credits.values()),
        ("recording_credits", m.RecordingCredit, batch.recording_credits.values()),
        ("artist_relations", m.ArtistRelation, batch.artist_relations.values()),
    ]
    for name, model, rows in fact_tables:
        counts[name] = sync_source_facts(
            session, model, _attach_provenance(rows, raw_ids, run_id), _ADAPTER_SOURCES
        )
    counts["entity_source_mappings"] = sync_source_facts(
        session, m.EntitySourceMapping, _with_run(batch.mappings.values(), run_id), _ADAPTER_SOURCES
    )
    counts["garbage_collected"] = _collect_garbage(session)
    return counts


def file_sha256(path: Path) -> str:
    """Returns the SHA-256 of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ingest_snapshot(engine: Engine, snapshot_path: Path) -> dict[str, Any]:
    """Ingests a snapshot into the database and returns the run statistics.

    Raises:
        Exception: Any failure is recorded on the run (status ``failed``) and
            re-raised; the data transaction is rolled back.
    """
    started = time.perf_counter()
    with session_scope(engine) as session:
        upsert(session, m.DataSource, DATA_SOURCES)
        run = m.IngestionRun(
            adapter=ADAPTER,
            pipeline_version=PIPELINE_VERSION,
            snapshot_sha256=file_sha256(snapshot_path),
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
            if session.get_bind().dialect.name == "postgresql":
                session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"), {"key": _INGEST_LOCK_KEY}
                )
            counts = write_batch(session, batch, records, run_id)
            session.flush()
            quality = run_quality_checks(session)
            if not gate_passes(quality):
                failing = sorted(
                    f"{r.name}={r.violations}"
                    for r in quality
                    if r.severity is Severity.ERROR and not r.passed
                )
                raise QualityGateError(f"quality gate failed: {', '.join(failing)}")
            elapsed = time.perf_counter() - started
            stats: dict[str, Any] = {
                "runId": run_id,
                "pipelineVersion": PIPELINE_VERSION,
                "records": len(records),
                "recordsPerSecond": round(len(records) / elapsed, 1) if elapsed else None,
                "elapsedSeconds": round(elapsed, 2),
                "batch": dict(sorted(batch.stats.items())),
                "rejected": batch.rejected,
                "ignoredRelationTypes": dict(batch.ignored_relation_types.most_common()),
                "writes": counts,
                "quality": {r.name: r.violations for r in quality},
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
    log.info("ingestion succeeded", extra={"run_id": run_id, "elapsed_s": stats["elapsedSeconds"]})
    return stats
