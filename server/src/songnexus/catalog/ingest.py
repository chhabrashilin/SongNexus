"""Persist a canonical batch, recording the run and provenance.

Write semantics:

* Facts (credits, relations, aliases, links, genre and label associations) and
  entity source mappings use source-scoped sync: after a run, the facts
  attributed to a source are exactly those in that source's snapshot. Stale facts
  are deleted, so the database is a pure function of its snapshots and
  re-ingestion is idempotent.
* Entities are upserted by their deterministic IDs. An entity no source maps to
  any more (and a genre neither mapped nor carried) is garbage-collected after
  the sync.
* MusicBrainz is the primary snapshot. Wikidata and Discogs snapshots enrich it
  (``catalog.enrich``); when they are absent their facts sync to empty, so the
  catalog is still a pure function of the snapshots given.
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
from dataclasses import dataclass
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
from songnexus.catalog.enrich import (
    ACOUSTICBRAINZ_SOURCE_ID,
    DISCOGS_SOURCE_ID,
    LISTENBRAINZ_SOURCE_ID,
    WIKIDATA_SOURCE_ID,
    EnrichmentBatch,
    GenreMap,
    build_enrichment,
)
from songnexus.catalog.quality import Severity, gate_passes, run_quality_checks
from songnexus.catalog.snapshot import RawRecord, read_snapshot
from songnexus.catalog.sources import BY_ID, Status, catalog_sources
from songnexus.storage import models as m
from songnexus.storage.db import session_scope

log = logging.getLogger(__name__)

ADAPTER = "musicbrainz"
CHUNK = 500
# Arbitrary, stable key for pg_advisory_xact_lock ("songnexus ingest").
_INGEST_LOCK_KEY = 0x5309_1A6E


class QualityGateError(RuntimeError):
    """The new catalog violates an error-severity invariant; nothing was written."""


class UnregisteredSourceError(ValueError):
    """A fact names a source that is not an in-use catalog source in the registry (ADR 0005)."""


# The sources ingest writes; each must be an in-use catalog source in the registry.
_MUSICBRAINZ_SOURCES = (SOURCE_ID, SUPPLEMENTARY_SOURCE_ID)
_ENRICHMENT_SOURCES = (
    DISCOGS_SOURCE_ID,
    WIKIDATA_SOURCE_ID,
    ACOUSTICBRAINZ_SOURCE_ID,
    LISTENBRAINZ_SOURCE_ID,
)
_INGESTED_SOURCES = (*_MUSICBRAINZ_SOURCES, *_ENRICHMENT_SOURCES)
_STORABLE = frozenset(s.id for s in catalog_sources() if s.status is Status.IN_USE)


@dataclass(frozen=True)
class EnrichmentInputs:
    """The enrichment snapshots and the reviewed genre table."""

    wikidata_snapshot: Path
    discogs_snapshot: Path
    genre_map: Path
    acousticbrainz_snapshot: Path | None = None
    listenbrainz_snapshot: Path | None = None


def registered_source_rows(source_ids: Iterable[str] = _INGESTED_SOURCES) -> list[Row]:
    """Returns ``data_sources`` rows for ``source_ids``, from the registry.

    Raises:
        UnregisteredSourceError: A source is missing, evaluation-only, or not yet in use.
    """
    rows = []
    for source_id in source_ids:
        if source_id not in _STORABLE:
            raise UnregisteredSourceError(f"source {source_id!r} may not be stored in the catalog")
        source = BY_ID[source_id]
        rows.append(
            {
                "id": source.id,
                "name": source.name,
                "homepage": source.homepage,
                "license": source.license,
            }
        )
    return rows


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


def _attach_provenance(
    rows: Iterable[Row], raw_ids: dict[str, dict[str, int]], run_id: int, sources: Sequence[str]
) -> list[Row]:
    """Resolves each row's raw key to its raw record, refusing rows from other sources."""
    attached = []
    for row in rows:
        if row["source_id"] not in sources:
            raise UnregisteredSourceError(f"fact from unexpected source {row['source_id']!r}")
        out = {k: v for k, v in row.items() if k != "_raw_key"}
        # Supplementary facts are asserted by MusicBrainz raw records.
        raw_source = SOURCE_ID if row["source_id"] in _MUSICBRAINZ_SOURCES else row["source_id"]
        out["raw_record_id"] = raw_ids[raw_source][row["_raw_key"]]
        out["ingestion_run_id"] = run_id
        attached.append(out)
    return attached


def _with_run(rows: Iterable[Row], run_id: int) -> list[Row]:
    return [{**row, "ingestion_run_id": run_id} for row in rows]


def _write_raw_records(
    session: Session, records: list[RawRecord], run_id: int, source_id: str
) -> dict[str, int]:
    """Upserts one source's raw records by request key and returns request key -> row ID."""

    def current_ids() -> dict[str, int]:
        stmt = select(m.RawRecord.request_key, m.RawRecord.id).where(
            m.RawRecord.source_id == source_id
        )
        return dict(session.execute(stmt).all())

    rows = [
        {
            "source_id": source_id,
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
    """Deletes entities nothing maps to, and genres neither in the vocabulary nor carried."""
    deleted: dict[str, int] = {}
    for entity_type, model in m.ENTITY_MODELS.items():
        mapped = select(m.EntitySourceMapping.entity_id).where(
            m.EntitySourceMapping.entity_type == entity_type
        )
        entity_id = model.id  # type: ignore[attr-defined]
        result = session.execute(delete(model).where(entity_id.not_in(mapped)))
        deleted[entity_type] = int(result.rowcount)  # type: ignore[attr-defined]
    carried = select(m.ArtistGenre.genre_id)
    in_vocabulary = select(m.EntitySourceMapping.entity_id).where(
        m.EntitySourceMapping.entity_type == "genre"
    )
    result = session.execute(
        delete(m.Genre).where(m.Genre.id.not_in(carried), m.Genre.id.not_in(in_vocabulary))
    )
    deleted["genre"] = int(result.rowcount)  # type: ignore[attr-defined]
    return deleted


def write_batch(
    session: Session,
    batch: CanonicalBatch,
    records: dict[str, list[RawRecord]],
    run_id: int,
    enrichment: EnrichmentBatch | None = None,
) -> dict[str, Any]:
    """Writes a batch (and its enrichment) in dependency order; returns write counts.

    Args:
        session: The open transaction.
        batch: The MusicBrainz batch.
        records: Raw records by source ID; sources absent here have none.
        run_id: The ingestion run.
        enrichment: Discogs and Wikidata rows; none when omitted.
    """
    enrichment = enrichment or EnrichmentBatch()
    raw_ids = {
        source_id: _write_raw_records(session, records.get(source_id, []), run_id, source_id)
        for source_id in (SOURCE_ID, *_ENRICHMENT_SOURCES)
    }
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
            session,
            model,
            _attach_provenance(rows, raw_ids, run_id, _MUSICBRAINZ_SOURCES),
            _MUSICBRAINZ_SOURCES,
        )
    counts["entity_source_mappings"] = sync_source_facts(
        session,
        m.EntitySourceMapping,
        _with_run(batch.mappings.values(), run_id),
        _MUSICBRAINZ_SOURCES,
    )

    # Enrichment: Discogs genres and artist mappings, Wikidata genre parents.
    counts["discogs_artist_genres"] = sync_source_facts(
        session,
        m.ArtistGenre,
        _attach_provenance(
            enrichment.artist_genres.values(), raw_ids, run_id, (DISCOGS_SOURCE_ID,)
        ),
        (DISCOGS_SOURCE_ID,),
    )
    counts["genre_parents"] = sync_source_facts(
        session,
        m.GenreParent,
        _attach_provenance(
            enrichment.genre_parents.values(), raw_ids, run_id, (WIKIDATA_SOURCE_ID,)
        ),
        (WIKIDATA_SOURCE_ID,),
    )
    counts["recording_descriptors"] = sync_source_facts(
        session,
        m.RecordingDescriptors,
        _attach_provenance(
            enrichment.descriptors.values(), raw_ids, run_id, (ACOUSTICBRAINZ_SOURCE_ID,)
        ),
        (ACOUSTICBRAINZ_SOURCE_ID,),
    )
    for name, model, rows in (
        ("artist_audiences", m.ArtistAudience, enrichment.audiences.values()),
        ("artist_colistening", m.ArtistCoListening, enrichment.colistening.values()),
    ):
        counts[name] = sync_source_facts(
            session,
            model,
            _attach_provenance(rows, raw_ids, run_id, (LISTENBRAINZ_SOURCE_ID,)),
            (LISTENBRAINZ_SOURCE_ID,),
        )
    counts["discogs_entity_source_mappings"] = sync_source_facts(
        session,
        m.EntitySourceMapping,
        _with_run(enrichment.mappings.values(), run_id),
        (DISCOGS_SOURCE_ID,),
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


def _read_enrichment(
    batch: CanonicalBatch, inputs: EnrichmentInputs | None
) -> tuple[EnrichmentBatch, dict[str, list[RawRecord]]]:
    if inputs is None:
        return EnrichmentBatch(), {}
    records = {
        WIKIDATA_SOURCE_ID: list(read_snapshot(inputs.wikidata_snapshot)),
        DISCOGS_SOURCE_ID: list(read_snapshot(inputs.discogs_snapshot)),
        ACOUSTICBRAINZ_SOURCE_ID: (
            list(read_snapshot(inputs.acousticbrainz_snapshot))
            if inputs.acousticbrainz_snapshot
            else []
        ),
        LISTENBRAINZ_SOURCE_ID: (
            list(read_snapshot(inputs.listenbrainz_snapshot))
            if inputs.listenbrainz_snapshot
            else []
        ),
    }
    enrichment = build_enrichment(
        batch,
        records[WIKIDATA_SOURCE_ID],
        records[DISCOGS_SOURCE_ID],
        GenreMap.load(inputs.genre_map),
        acousticbrainz_records=records[ACOUSTICBRAINZ_SOURCE_ID],
        listenbrainz_records=records[LISTENBRAINZ_SOURCE_ID],
    )
    return enrichment, records


def ingest_snapshot(
    engine: Engine, snapshot_path: Path, enrichment_inputs: EnrichmentInputs | None = None
) -> dict[str, Any]:
    """Ingests a snapshot (and optional enrichment) and returns the run statistics.

    Raises:
        Exception: Any failure is recorded on the run (status ``failed``) and
            re-raised; the data transaction is rolled back.
    """
    started = time.perf_counter()
    with session_scope(engine) as session:
        upsert(session, m.DataSource, registered_source_rows())
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
        enrichment, enrichment_records = _read_enrichment(batch, enrichment_inputs)
        with session_scope(engine) as session:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"), {"key": _INGEST_LOCK_KEY}
                )
            counts = write_batch(
                session, batch, {SOURCE_ID: records, **enrichment_records}, run_id, enrichment
            )
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
                "enrichment": {
                    **dict(sorted(enrichment.stats.items())),
                    "unmappedDiscogsNames": dict(enrichment.unmapped_names.most_common(25)),
                },
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
        if isinstance(exc, QualityGateError):
            # An expected rejection, not a crash: one line, no stack trace.
            log.error("ingestion rejected by the quality gate: %s", exc, extra={"run_id": run_id})
        else:
            log.exception("ingestion failed", extra={"run_id": run_id})
        raise
    log.info("ingestion succeeded", extra={"run_id": run_id, "elapsed_s": stats["elapsedSeconds"]})
    return stats
