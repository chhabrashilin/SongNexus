from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from songnexus.api.app import create_app
from songnexus.core.config import Settings
from songnexus.core.metrics import metrics
from songnexus.db.session import create_all, make_engine
from songnexus.integrations.musicbrainz.snapshot import write_snapshot
from songnexus.pipelines.ingest import ingest_snapshot
from tests.fixtures import synthetic_records


def memory_engine() -> Engine:
    engine = make_engine("sqlite://")
    create_all(engine)
    return engine


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    metrics.reset()


@pytest.fixture
def snapshot_path(tmp_path: Path) -> Path:
    path = tmp_path / "snapshot.jsonl.gz"
    write_snapshot(synthetic_records(), path)
    return path


@pytest.fixture
def engine() -> Engine:
    return memory_engine()


@pytest.fixture
def loaded_engine(engine: Engine, snapshot_path: Path) -> Engine:
    ingest_snapshot(engine, snapshot_path)
    return engine


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite://",
        log_json=False,
        warm_analytics=False,
        agent_rate_limit_per_minute=1000,
        admin_token="test-admin-token",
    )


@pytest.fixture
def client(loaded_engine: Engine, settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings=settings, engine=loaded_engine, llm_client=None)
    with TestClient(app) as test_client:
        yield test_client
