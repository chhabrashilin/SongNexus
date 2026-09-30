"""Regression guards on the committed MusicBrainz sample snapshot (offline).

Thresholds sit slightly below the values measured when the snapshot was
committed (docs/evaluation.md), so they catch regressions without flaking.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from songnexus.core.config import REPO_ROOT, Settings
from songnexus.core.ids import artist_id_for_mbid
from songnexus.db.session import session_scope
from songnexus.evaluation.agent_eval import run_agent_eval
from songnexus.evaluation.search_eval import run_search_eval
from songnexus.graph.projection import DEFAULT_CATEGORIES
from songnexus.pipelines.ingest import ingest_snapshot
from songnexus.pipelines.quality import run_quality_checks
from songnexus.readmodel import ReadModelStore
from songnexus.services.graph_service import GraphService
from tests.conftest import memory_engine

pytestmark = pytest.mark.sample_data
SNAPSHOT = REPO_ROOT / "data" / "samples" / "musicbrainz_snapshot.jsonl.gz"
EVAL = REPO_ROOT / "evaluation"
KENDRICK = artist_id_for_mbid("381086ea-f511-4aba-bdf9-71c753dc5077")
SZA = artist_id_for_mbid("272989c8-5535-492d-a25c-9f58803e027f")
MILES = artist_id_for_mbid("561d854a-6a28-4aa7-8c99-323e6ce46c2a")
DRAKE = artist_id_for_mbid("9fff2f8a-21e6-47de-a2b8-7f449929d43f")


@pytest.fixture(scope="module")
def sample_engine() -> Engine:
    if not SNAPSHOT.exists():
        pytest.skip("sample snapshot not present")
    engine = memory_engine()
    ingest_snapshot(engine, SNAPSHOT)
    return engine


@pytest.fixture(scope="module")
def service(sample_engine: Engine) -> GraphService:
    return GraphService(ReadModelStore(sample_engine), Settings(database_url="sqlite://", warm_analytics=False))


def test_all_quality_checks_pass(sample_engine: Engine) -> None:
    with session_scope(sample_engine) as session:
        assert [r.name for r in run_quality_checks(session) if not r.passed] == []


def test_graph_size_is_plausible(service: GraphService) -> None:
    stats = service.stats()
    assert stats.hydrated_artists == 28
    assert stats.artists > 2000 and stats.edges > 4000
    assert stats.largest_component > 1500


def test_known_direct_connection_has_evidence(service: GraphService) -> None:
    evidence = service.edge_evidence(KENDRICK, SZA, DEFAULT_CATEGORIES)
    assert any(e.subject_title == "Doves in the Wind" for e in evidence.evidence)


def test_cross_genre_path_exists(service: GraphService) -> None:
    result = service.path(MILES, DRAKE, "shortest", DEFAULT_CATEGORIES, max_depth=6, alternatives=0)
    assert result.found and result.path is not None and result.path.length <= 6


def test_search_quality_floor(sample_engine: Engine) -> None:
    report = run_search_eval(EVAL / "search_cases.json", k=5, engine=sample_engine)
    lexical = report["systems"]["lexical_ranker"]["overall"]
    baseline = report["systems"]["exact_baseline"]["overall"]
    assert lexical["mrr"] >= 0.95
    assert lexical["recall_at_5"] >= 0.95
    assert lexical["mrr"] > baseline["mrr"]


def test_deterministic_agent_quality_floor(sample_engine: Engine) -> None:
    report = run_agent_eval(EVAL / "agent_cases.json", mode="deterministic", engine=sample_engine)
    metrics = report["metrics"]
    assert metrics["unsupported_claim_rate"] == 0.0
    assert metrics["limitation_admission"] == 1.0
    assert metrics["task_success_rate"] >= 0.85
