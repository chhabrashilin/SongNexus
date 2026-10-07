"""The same migrations, ingest and quality gate on PostgreSQL (the production database).

Runs only when SONGNEXUS_TEST_DATABASE_URL points at a disposable database; CI
provides one. The database is wiped (downgraded to empty) before and after.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import inspect

from songnexus.catalog.ingest import ingest_snapshot
from songnexus.catalog.musicbrainz.snapshot import write_snapshot
from songnexus.catalog.quality import gate_passes, run_quality_checks
from songnexus.storage import migrate
from songnexus.storage.db import make_engine, session_scope
from tests.catalog import fixtures as fx

DATABASE_URL = os.environ.get("SONGNEXUS_TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not DATABASE_URL, reason="SONGNEXUS_TEST_DATABASE_URL is not set"),
]


def test_ingest_and_quality_gate_on_postgres(tmp_path: Path) -> None:
    engine = make_engine(DATABASE_URL)
    migrate.downgrade(engine, "base")
    try:
        migrate.upgrade(engine)
        snapshot = tmp_path / "snapshot.jsonl.gz"
        write_snapshot(fx.small_catalog(), snapshot)
        first = ingest_snapshot(engine, snapshot)
        second = ingest_snapshot(engine, snapshot)
        assert first["rejected"] == second["rejected"] == []
        with session_scope(engine) as session:
            assert gate_passes(run_quality_checks(session))
    finally:
        migrate.downgrade(engine, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
