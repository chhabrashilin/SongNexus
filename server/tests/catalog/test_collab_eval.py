"""The collaborations recall check finds what the pipeline shows, and notices what it drops."""

from pathlib import Path

from songnexus.catalog.collab_eval import collaboration_recall, raw_collaborators
from songnexus.catalog.ingest import ingest_snapshot
from songnexus.catalog.snapshot import write_snapshot
from songnexus.core.graph.collaborations import CollaborationType
from songnexus.core.graph.model import ArtistGraph, EdgeKind
from songnexus.core.graph.projection import build_graph
from songnexus.storage import migrate
from songnexus.storage.catalog_reader import read_catalog_facts
from songnexus.storage.db import make_engine, session_scope
from tests.catalog import fixtures as fx

ARTISTS = ["mb-alice", "mb-bob", "mb-carol"]


def _graph(tmp_path: Path) -> ArtistGraph:
    snapshot = tmp_path / "snap.jsonl.gz"
    write_snapshot(fx.small_catalog(), snapshot)
    engine = make_engine(f"sqlite:///{tmp_path / 'catalog.db'}")
    migrate.upgrade(engine)
    ingest_snapshot(engine, snapshot)
    with session_scope(engine) as session:
        facts = read_catalog_facts(session)
    return build_graph(facts, "test")


def test_raw_collaborators_follow_the_product_definitions() -> None:
    pairs = raw_collaborators(fx.small_catalog())
    assert pairs[CollaborationType.FEATURE]["mb-alice"] == {"mb-bob"}
    assert pairs[CollaborationType.PRODUCTION]["mb-carol"] == {"mb-alice", "mb-bob"}
    assert pairs[CollaborationType.BAND]["mb-alice"] == {"mb-band"}


def test_full_recall_on_the_fixture(tmp_path: Path) -> None:
    report = collaboration_recall(_graph(tmp_path), fx.small_catalog(), ARTISTS)
    assert report.overall == 1.0
    assert report.by_type["PRODUCTION"].expected == 4  # Carol-Alice and Carol-Bob, both ways


def test_a_dropped_collaboration_is_noticed(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    # Drop the production evidence, as a pipeline bug would.
    for edge in graph.edges.values():
        edge.evidence[:] = [e for e in edge.evidence if e.kind is not EdgeKind.PRODUCED_FOR]
    report = collaboration_recall(graph, fx.small_catalog(), ARTISTS)
    production = report.by_type["PRODUCTION"]
    assert production.recall == 0.0
    assert production.missing_examples
    assert report.overall is not None
    assert report.overall < 1.0
