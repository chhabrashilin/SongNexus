"""Golden tests: the committed MusicBrainz, Wikidata and Discogs snapshots ingest together.

The coverage floors are set just under the first measurement (2026-11-01, recorded
in docs/handoff/evaluations.md): they catch a broken join or mapping, not noise.
"""

from pathlib import Path

import pytest
from sqlalchemy import Engine, select

from songnexus.catalog.canonicalize import SUPPLEMENTARY_SOURCE_ID, build_batch
from songnexus.catalog.enrich import DISCOGS_SOURCE_ID, GenreMap
from songnexus.catalog.ingest import EnrichmentInputs, ingest_snapshot
from songnexus.catalog.quality import gate_passes, run_quality_checks
from songnexus.catalog.snapshot import read_snapshot
from songnexus.core.graph.genre_eval import genre_agreement
from songnexus.service.readmodel import load_read_model
from songnexus.storage import migrate
from songnexus.storage import models as m
from songnexus.storage.db import make_engine, session_scope

DATA = Path(__file__).resolve().parents[3] / "data"
MUSICBRAINZ = DATA / "samples" / "musicbrainz_snapshot.jsonl.gz"
WIKIDATA = DATA / "samples" / "wikidata_snapshot.jsonl.gz"
DISCOGS = DATA / "samples" / "discogs_snapshot.jsonl.gz"
GENRE_MAP = DATA / "seeds" / "discogs_genre_map.json"

MIN_ARTISTS_WITH_GENRES = 1700  # measured 1,764
MIN_TOP1_AGREEMENT_WITH_HIERARCHY = 0.90  # measured 0.942

pytestmark = [
    pytest.mark.golden,
    pytest.mark.skipif(
        not all(p.exists() for p in (MUSICBRAINZ, WIKIDATA, DISCOGS)),
        reason="committed snapshots not present",
    ),
]


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory) -> Engine:
    engine = make_engine(f"sqlite:///{tmp_path_factory.mktemp('enriched') / 'catalog.db'}")
    migrate.upgrade(engine)
    ingest_snapshot(engine, MUSICBRAINZ, EnrichmentInputs(WIKIDATA, DISCOGS, GENRE_MAP))
    return engine


def test_the_enriched_catalog_passes_the_quality_gate(engine: Engine) -> None:
    with session_scope(engine) as session:
        assert gate_passes(run_quality_checks(session))
        stats = session.scalars(select(m.IngestionRun.stats)).one()
    assert stats["rejected"] == []
    assert stats["enrichment"]["artists_linked_to_discogs"] > 2000


def test_every_reviewed_mapping_names_a_real_genre() -> None:
    batch = build_batch(read_snapshot(MUSICBRAINZ))
    vocabulary = {row["normalized_name"] for row in batch.genres.values()}
    genre_map = GenreMap.load(GENRE_MAP)
    missing = {
        name: targets
        for name, targets in genre_map.mapped.items()
        if not set(targets) <= vocabulary
    }
    assert missing == {}


def test_genre_coverage_and_agreement_hold(engine: Engine) -> None:
    report = genre_agreement(
        load_read_model(engine, [SUPPLEMENTARY_SOURCE_ID]).graph,
        load_read_model(engine, [DISCOGS_SOURCE_ID]).graph,
    )
    assert report.covered_either >= MIN_ARTISTS_WITH_GENRES
    assert report.top1_hierarchy is not None
    assert report.top1_hierarchy >= MIN_TOP1_AGREEMENT_WITH_HIERARCHY
