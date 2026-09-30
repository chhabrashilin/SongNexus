"""Stages 5-6 against a real (in-memory SQLite) database."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select

from songnexus.db import models as m
from songnexus.db.session import session_scope
from songnexus.integrations.musicbrainz.snapshot import write_snapshot
from songnexus.pipelines.ingest import ingest_snapshot
from songnexus.pipelines.quality import run_quality_checks
from tests.fixtures import synthetic_records

FACT_TABLES = (m.TrackCredit, m.ArtistRelationship, m.ArtistAlias, m.AlbumTrack, m.EntitySourceMapping)


def counts(engine: Engine) -> dict[str, int]:
    with session_scope(engine) as s:
        return {
            model.__tablename__: s.scalar(select(func.count()).select_from(model)) or 0
            for model in (m.Artist, m.Track, m.Album, *FACT_TABLES)
        }


def test_ingest_populates_all_layers(engine: Engine, snapshot_path: Path) -> None:
    stats = ingest_snapshot(engine, snapshot_path)
    c = counts(engine)
    assert c["artists"] == 8
    assert c["tracks"] == 3  # Skyline (two recordings merged), Nocturne, Alone Again
    assert c["albums"] == 4
    assert c["artist_relationships"] == 2
    assert stats["rejected"] == []
    with session_scope(engine) as s:
        run = s.scalars(select(m.IngestionRun)).one()
        assert run.status == "succeeded" and run.snapshot_sha256 and run.pipeline_version


def test_reingesting_the_same_snapshot_is_idempotent(engine: Engine, snapshot_path: Path) -> None:
    ingest_snapshot(engine, snapshot_path)
    before = counts(engine)
    stats = ingest_snapshot(engine, snapshot_path)
    assert counts(engine) == before
    for table, write in stats["writes"].items():
        assert write["inserted"] == 0, table
        assert write.get("deleted", 0) == 0, table


def test_facts_removed_from_the_source_are_deleted(engine: Engine, snapshot_path: Path, tmp_path: Path) -> None:
    ingest_snapshot(engine, snapshot_path)
    without_zeta = [
        r for r in synthetic_records() if not r.request_key.startswith("artist/") or "Zeta" not in r.body["name"]
    ]
    smaller = tmp_path / "smaller.jsonl.gz"
    write_snapshot(without_zeta, smaller)
    stats = ingest_snapshot(engine, smaller)
    assert (
        stats["writes"]["artist_relationships"]["deleted"] == 1
    )  # epsilon -member_of-> zeta came only from zeta's lookup
    # Entities are never deleted by ingestion (other sources may reference them).
    assert counts(engine)["artists"] == 8


def test_every_fact_has_provenance_back_to_a_raw_record(loaded_engine: Engine) -> None:
    with session_scope(loaded_engine) as s:
        for model in (m.TrackCredit, m.ArtistRelationship, m.ArtistAlias):
            for fact in s.scalars(select(model)):
                raw = s.get(m.RawRecord, fact.raw_record_id)
                run = s.get(m.IngestionRun, fact.ingestion_run_id)
                assert raw is not None and raw.url.startswith("https://")
                assert run is not None and run.status == "succeeded"
                assert fact.source_id == "musicbrainz"


def test_quality_checks_pass_on_ingested_data(loaded_engine: Engine) -> None:
    with session_scope(loaded_engine) as s:
        failures = [r for r in run_quality_checks(s) if not r.passed]
    assert failures == []


def test_quality_checks_detect_violations(loaded_engine: Engine) -> None:
    with session_scope(loaded_engine) as s:
        credit = s.scalars(select(m.TrackCredit)).first()
        assert credit is not None
        credit.confidence = 1.5
        s.flush()
        results = {r.name: r for r in run_quality_checks(s)}
        assert not results["credit_confidence_range"].passed
        s.rollback()


def test_failed_run_is_recorded(engine: Engine, tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl.gz"
    bad.write_bytes(b"not gzip at all")
    with pytest.raises(OSError):
        ingest_snapshot(engine, bad)
    with session_scope(engine) as s:
        run = s.scalars(select(m.IngestionRun)).one()
        assert run.status == "failed" and run.error
