"""Golden tests: the committed MusicBrainz snapshot ingests cleanly and reproducibly."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select

from songnexus.catalog.ingest import ingest_snapshot
from songnexus.catalog.quality import Severity, run_quality_checks
from songnexus.storage import migrate
from songnexus.storage import models as m
from songnexus.storage.db import make_engine, session_scope

SNAPSHOT = (
    Path(__file__).resolve().parents[3] / "data" / "samples" / "musicbrainz_snapshot.jsonl.gz"
)

pytestmark = [
    pytest.mark.golden,
    pytest.mark.skipif(not SNAPSHOT.exists(), reason="committed snapshot not present"),
]


def _ingested(path: Path) -> Engine:
    engine = make_engine(f"sqlite:///{path}")
    migrate.upgrade(engine)
    ingest_snapshot(engine, SNAPSHOT)
    return engine


def _rows(engine: Engine, columns: list[Any]) -> list[tuple[str, ...]]:
    with session_scope(engine) as session:
        return sorted(tuple(map(str, r)) for r in session.execute(select(*columns)))


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory) -> Engine:
    return _ingested(tmp_path_factory.mktemp("golden") / "catalog.db")


def test_snapshot_passes_the_quality_gate(engine: Engine) -> None:
    with session_scope(engine) as session:
        results = run_quality_checks(session)
    errors = {
        r.name: r.violations for r in results if r.severity is Severity.ERROR and not r.passed
    }
    assert errors == {}


def test_no_records_rejected(engine: Engine) -> None:
    with session_scope(engine) as session:
        run = session.scalars(select(m.IngestionRun)).one()
    assert run.stats["rejected"] == []


def test_catalog_is_not_trivially_small(engine: Engine) -> None:
    with session_scope(engine) as session:
        artists = session.scalar(select(func.count()).select_from(m.Artist))
        credits = session.scalar(select(func.count()).select_from(m.RecordingCredit))
    assert artists is not None
    assert artists > 100
    assert credits is not None
    assert credits > artists


def test_ingest_is_reproducible(engine: Engine, tmp_path: Path) -> None:
    """Two independent ingests of the same snapshot yield identical canonical content."""
    other = _ingested(tmp_path / "again.db")
    tables = (m.Artist, m.Release, m.Recording, m.Genre, m.ArtistRelation, m.RecordingCredit)
    for model in tables:
        table = m.Base.metadata.tables[model.__tablename__]
        columns = [c for c in table.columns if c.name != "ingestion_run_id"]
        assert _rows(engine, columns) == _rows(other, columns), table.name


def test_search_meets_the_mrr_gate(engine: Engine) -> None:
    """The plan's evaluation gate: MRR >= 0.95 on the labeled set, every label mapped."""
    import json

    from songnexus.cli import MIN_SEARCH_MRR
    from songnexus.core.search import EvalCase, evaluate
    from songnexus.service.readmodel import load_read_model
    from songnexus.storage.catalog_reader import canonical_ids_for_sources

    cases_path = SNAPSHOT.parents[1] / "eval" / "search_cases.json"
    raw = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    with session_scope(engine) as session:
        canonical = canonical_ids_for_sources(
            session, [r["mbid"] for c in raw for r in c["relevant"]]
        )
    cases = [
        EvalCase(c["query"], c["category"], frozenset(canonical[r["mbid"]] for r in c["relevant"]))
        for c in raw
    ]
    report = evaluate(load_read_model(engine).search, cases)
    assert report.mrr >= MIN_SEARCH_MRR, report.misses


def test_import_matching_meets_the_precision_gate(engine: Engine) -> None:
    """AC-10.2: precision >= 0.98 on the labeled names; homonyms are never auto-matched."""
    from songnexus.cli import MIN_IMPORT_PRECISION, import_match_report

    report = import_match_report(engine, SNAPSHOT.parents[1] / "eval" / "import_match_cases.json")
    assert report.precision >= MIN_IMPORT_PRECISION, report.errors
    _, matched, _ = report.by_category["homonym"]
    assert matched == 0, [e for e in report.errors if e[2] is None]
