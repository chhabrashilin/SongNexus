"""The same ingestion guarantees on PostgreSQL (the production database).

Runs only when SONGNEXUS_TEST_DATABASE_URL points at a disposable database,
e.g. the service container in CI:
    SONGNEXUS_TEST_DATABASE_URL=postgresql+psycopg://songnexus:songnexus@localhost:5432/songnexus_test
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from songnexus.db.models import Base
from songnexus.db.session import create_all, make_engine, session_scope
from songnexus.pipelines.ingest import ingest_snapshot
from songnexus.pipelines.quality import run_quality_checks

URL = os.environ.get("SONGNEXUS_TEST_DATABASE_URL")
pytestmark = [pytest.mark.postgres, pytest.mark.skipif(not URL, reason="SONGNEXUS_TEST_DATABASE_URL not set")]


@pytest.fixture
def pg_engine() -> Iterator[Engine]:
    assert URL is not None
    engine = make_engine(URL)
    Base.metadata.drop_all(engine)
    create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_ingest_is_idempotent_and_clean_on_postgres(pg_engine: Engine, snapshot_path: Path) -> None:
    ingest_snapshot(pg_engine, snapshot_path)
    second = ingest_snapshot(pg_engine, snapshot_path)
    assert all(w["inserted"] == 0 and w.get("deleted", 0) == 0 for w in second["writes"].values())
    with session_scope(pg_engine) as session:
        assert [r.name for r in run_quality_checks(session) if not r.passed] == []
        column_type = session.execute(
            text(
                "select data_type from information_schema.columns "
                "where table_name = 'raw_records' and column_name = 'payload'"
            )
        ).scalar()
    assert column_type == "jsonb"
