"""The data-source registry (ADR 0005): its invariants, and that ingest enforces it."""

import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, select, union
from sqlalchemy.orm import Session

from songnexus.catalog import sources
from songnexus.catalog.ingest import (
    UnregisteredSourceError,
    ingest_snapshot,
    registered_source_rows,
)
from songnexus.catalog.snapshot import write_snapshot
from songnexus.catalog.sources import SOURCES, Kind, Status, Tier, render_markdown
from songnexus.storage import migrate
from songnexus.storage import models as m
from songnexus.storage.db import make_engine
from tests.catalog import fixtures as fx


def test_ids_are_unique_and_stable() -> None:
    ids = [s.id for s in SOURCES]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", i) for i in ids)


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.id)
def test_every_source_states_its_license_and_purpose(source: sources.DataSource) -> None:
    assert source.license.strip()
    assert source.license_url.startswith(("https://", "/"))
    assert source.homepage.startswith(("https://", "/"))
    assert source.feeds, "a source nobody reads should not be registered"
    assert date.fromisoformat(source.checked_on) <= date.today()


def test_evaluation_sources_are_never_storable() -> None:
    storable = {s.id for s in sources.catalog_sources()}
    for source in SOURCES:
        if source.tier is Tier.EVALUATION or source.kind is Kind.USER_ACCOUNT:
            assert source.id not in storable


def test_ingest_registers_only_in_use_catalog_sources() -> None:
    rows = registered_source_rows()
    assert {r["id"] for r in rows} == {
        "musicbrainz",
        "musicbrainz-supplementary",
        "discogs",
        "wikidata",
        "acousticbrainz",
        "listenbrainz",
    }
    with pytest.raises(UnregisteredSourceError):
        registered_source_rows(["kaggle-spotify-tracks"])
    with pytest.raises(UnregisteredSourceError):
        registered_source_rows(["lastfm-360k"])  # evaluation data never enters the catalog
    with pytest.raises(UnregisteredSourceError):
        registered_source_rows(["made-up"])


@pytest.fixture
def ingested(tmp_path: Path) -> Engine:
    snapshot = tmp_path / "snapshot.jsonl.gz"
    write_snapshot(fx.small_catalog(), snapshot)
    engine = make_engine(f"sqlite:///{tmp_path / 'catalog.db'}")
    migrate.upgrade(engine)
    ingest_snapshot(engine, snapshot)
    return engine


def test_every_stored_fact_traces_to_an_in_use_registered_source(ingested: Engine) -> None:
    fact_models = [
        mdl
        for mdl in m.Base.__subclasses__()
        if hasattr(mdl, "source_id") and mdl is not m.DataSource
    ]
    assert len(fact_models) >= 10
    query = union(*(select(mdl.source_id) for mdl in fact_models))
    with Session(ingested) as session:
        used = set(session.scalars(query))
        registered = set(session.scalars(select(m.DataSource.id)))
    in_use = {s.id for s in SOURCES if s.status is Status.IN_USE}
    assert used <= registered <= in_use


def test_resources_page_is_generated_from_the_registry() -> None:
    page = render_markdown()
    for source in SOURCES:
        assert f"`{source.id}`" in page
    assert "Do not edit by hand" in page
