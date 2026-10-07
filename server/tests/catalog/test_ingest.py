from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, inspect, select

from songnexus.catalog.ingest import ingest_snapshot
from songnexus.catalog.musicbrainz.snapshot import RawRecord, write_snapshot
from songnexus.catalog.quality import Severity, gate_passes, run_quality_checks
from songnexus.storage import migrate
from songnexus.storage import models as m
from songnexus.storage.db import create_schema, make_engine, session_scope
from tests.catalog import fixtures as fx


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = make_engine(f"sqlite:///{tmp_path / 'catalog.db'}")
    migrate.upgrade(engine)
    return engine


def _snapshot(tmp_path: Path, records: list[RawRecord], name: str = "snap.jsonl.gz") -> Path:
    path = tmp_path / name
    write_snapshot(records, path)
    return path


def _count(engine: Engine, model: type[m.Base]) -> int:
    with session_scope(engine) as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _dump(engine: Engine) -> dict[str, list[tuple[Any, ...]]]:
    """Every catalog row except run bookkeeping, for equality comparisons."""
    skip = {"ingestion_run_id", "last_seen_run_id"}
    dump = {}
    with session_scope(engine) as session:
        for table in m.Base.metadata.sorted_tables:
            if table.name == "ingestion_runs":
                continue
            columns = [c for c in table.columns if c.name not in skip]
            dump[table.name] = sorted(
                tuple(map(str, row)) for row in session.execute(select(*columns))
            )
    return dump


def test_migrations_match_the_models(tmp_path: Path) -> None:
    migrated = make_engine(f"sqlite:///{tmp_path / 'migrated.db'}")
    migrate.upgrade(migrated)
    direct = make_engine(f"sqlite:///{tmp_path / 'direct.db'}")
    create_schema(direct)

    def shape(engine: Engine) -> dict[str, Any]:
        inspector = inspect(engine)
        return {
            t: (
                sorted(
                    (c["name"], str(c["type"]), c["nullable"]) for c in inspector.get_columns(t)
                ),
                sorted(str(i["name"]) for i in inspector.get_indexes(t)),
                sorted(str(u["column_names"]) for u in inspector.get_unique_constraints(t)),
            )
            for t in inspector.get_table_names()
            if t != "alembic_version"
        }

    assert shape(migrated) == shape(direct)
    assert migrate.current_revision(migrated) == migrate.head_revision(migrated)


def test_migrations_downgrade_to_empty(engine: Engine) -> None:
    migrate.downgrade(engine, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    migrate.upgrade(engine)
    assert "recordings" in inspect(engine).get_table_names()


def test_ingest_then_quality_gate_passes(engine: Engine, tmp_path: Path) -> None:
    stats = ingest_snapshot(engine, _snapshot(tmp_path, fx.small_catalog()))
    assert stats["records"] == 4
    assert stats["rejected"] == []
    assert _count(engine, m.Artist) == 4
    assert _count(engine, m.Recording) == 2
    assert _count(engine, m.Label) == 1
    with session_scope(engine) as session:
        results = run_quality_checks(session)
        run = session.scalars(select(m.IngestionRun)).one()
    failing = [r.name for r in results if not r.passed and r.severity is Severity.ERROR]
    assert failing == []
    assert gate_passes(results)
    assert run.status == "succeeded"


def test_reingesting_the_same_snapshot_changes_nothing(engine: Engine, tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path, fx.small_catalog())
    ingest_snapshot(engine, snapshot)
    first = _dump(engine)
    stats = ingest_snapshot(engine, snapshot)
    assert _dump(engine) == first
    assert all(
        c.get("inserted", 0) == 0
        for c in stats["writes"].values()
        if isinstance(c, dict) and "inserted" in c
    )


def test_stale_facts_and_orphaned_entities_are_removed(engine: Engine, tmp_path: Path) -> None:
    ingest_snapshot(engine, _snapshot(tmp_path, fx.small_catalog()))
    without_best_of = [r for r in fx.small_catalog() if r.request_key != "release/rel-2"]
    stats = ingest_snapshot(engine, _snapshot(tmp_path, without_best_of, "smaller.jsonl.gz"))

    assert _count(engine, m.Release) == 1
    assert stats["writes"]["garbage_collected"]["release"] == 1
    # The merged remaster mapping went away; the canonical "Song" stays.
    with session_scope(engine) as session:
        merged = session.scalars(
            select(m.EntitySourceMapping).where(m.EntitySourceMapping.decision == "merged")
        ).all()
        assert merged == []
        assert gate_passes(run_quality_checks(session))


def test_ingest_from_scratch_matches_incremental_ingest(engine: Engine, tmp_path: Path) -> None:
    """The database is a pure function of the latest snapshot."""
    ingest_snapshot(engine, _snapshot(tmp_path, fx.small_catalog()[:2], "partial.jsonl.gz"))
    final = _snapshot(tmp_path, fx.small_catalog())
    ingest_snapshot(engine, final)

    fresh = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    migrate.upgrade(fresh)
    ingest_snapshot(fresh, final)

    incremental, scratch = _dump(engine), _dump(fresh)
    # Raw-record IDs are autoincrement surrogates and legitimately differ.
    for dump in (incremental, scratch):
        dump.pop("raw_records")
    assert incremental.keys() == scratch.keys()
    for table in incremental:
        if "raw_record_id" not in {c.name for c in m.Base.metadata.tables[table].columns}:
            assert incremental[table] == scratch[table], table


def test_failed_ingest_is_recorded(engine: Engine, tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.jsonl.gz"
    import gzip

    with gzip.open(corrupt, "wt", encoding="utf-8") as fh:
        fh.write("{not json}\n")
    with pytest.raises(ValueError, match="malformed snapshot record"):
        ingest_snapshot(engine, corrupt)
    with session_scope(engine) as session:
        run = session.scalars(select(m.IngestionRun)).one()
    assert run.status == "failed"
    assert run.error


def test_a_catalog_failing_the_quality_gate_is_never_published(
    engine: Engine, tmp_path: Path
) -> None:
    """QA Q3: the gate runs inside the ingest transaction."""
    from songnexus.catalog.ingest import QualityGateError
    from songnexus.storage.catalog_reader import catalog_version

    ingest_snapshot(engine, _snapshot(tmp_path, fx.small_catalog()))
    good = _dump(engine)
    with session_scope(engine) as session:
        good_version = catalog_version(session)

    # A recording with no artist credit violates recording_has_primary_artist.
    broken = fx.release_record(
        "rel-bad",
        "rg-bad",
        "Broken",
        fx.credit(("mb-alice", "Alice", "")),
        [fx.recording("rec-bad", "Nobody's Song", [])],
    )
    with pytest.raises(QualityGateError, match="recording_has_primary_artist"):
        ingest_snapshot(engine, _snapshot(tmp_path, [*fx.small_catalog(), broken], "bad.jsonl.gz"))

    assert _dump(engine) == good
    with session_scope(engine) as session:
        assert catalog_version(session) == good_version
        runs = session.scalars(select(m.IngestionRun).order_by(m.IngestionRun.id)).all()
    assert [r.status for r in runs] == ["succeeded", "failed"]
