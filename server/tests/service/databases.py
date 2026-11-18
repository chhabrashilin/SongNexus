"""Fresh databases for the user-data API tests: SQLite by default, PostgreSQL when asked.

With ``SONGNEXUS_TEST_DATABASE_URL`` set to a disposable PostgreSQL database (CI provides
one), the sign-in, linked-account and friends suites run on the production database
engine too. That database is wiped before every test, so never point it at real data.
"""

import os
from pathlib import Path

from sqlalchemy import Engine

from songnexus.catalog.ingest import ingest_snapshot
from songnexus.catalog.snapshot import write_snapshot
from songnexus.storage import migrate
from songnexus.storage.db import make_engine
from tests.catalog import fixtures as fx

POSTGRES_URL = os.environ.get("SONGNEXUS_TEST_DATABASE_URL", "")


def fresh_database_url(tmp_path: Path) -> str:
    """Returns the URL of an empty database for one test."""
    if not POSTGRES_URL:
        return f"sqlite:///{tmp_path / 'app.db'}"
    engine = make_engine(POSTGRES_URL)
    try:
        migrate.downgrade(engine, "base")
    finally:
        engine.dispose()
    return POSTGRES_URL


def migrated_with_catalog(url: str, tmp_path: Path) -> None:
    """Migrates ``url`` to head and loads the small test catalog."""
    snapshot = tmp_path / "snapshot.jsonl.gz"
    write_snapshot(fx.small_catalog(), snapshot)
    engine: Engine = make_engine(url)
    try:
        migrate.upgrade(engine)
        ingest_snapshot(engine, snapshot)
    finally:
        engine.dispose()
