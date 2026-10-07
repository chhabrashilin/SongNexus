"""The read model: the artist graph and search index for one catalog version.

Built once from the database after ingestion and shared read-only by every
request. A new catalog version builds a new read model; nothing mutates one.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine

from songnexus.core.graph.algorithms import weighted_degree
from songnexus.core.graph.model import DEFAULT_CATEGORIES, ArtistGraph, kinds_for
from songnexus.core.graph.projection import build_graph
from songnexus.core.search import EntityType, SearchDoc, SearchIndex, log_prior
from songnexus.service.errors import ApiError, Status
from songnexus.storage.catalog_reader import (
    SearchEntry,
    catalog_version,
    read_catalog_facts,
    read_search_entries,
)
from songnexus.storage.db import session_scope

log = logging.getLogger(__name__)


class EmptyCatalogError(RuntimeError):
    """No successful ingestion run exists, so there is nothing to serve."""


@dataclass(frozen=True)
class ReadModel:
    """Everything request handlers read, for one catalog version."""

    version: str
    graph: ArtistGraph
    search: SearchIndex


def _subtitle(entry: SearchEntry) -> str:
    parts = [", ".join(entry.artist_names), entry.detail or ""]
    return " · ".join(p for p in parts if p)


def build_search_index(entries: list[SearchEntry], graph: ArtistGraph) -> SearchIndex:
    """Builds the search index; artist priors come from weighted graph degree."""
    degree = weighted_degree(graph.adjacency(kinds_for(DEFAULT_CATEGORIES)))
    max_degree = max(degree.values(), default=0.0)
    max_popularity = {
        t: max((e.popularity for e in entries if e.entity_type == t), default=0)
        for t in ("release", "recording")
    }
    index = SearchIndex()
    for entry in entries:
        if entry.entity_type == "artist":
            prior = log_prior(degree.get(entry.entity_id, 0.0), max_degree)
        else:
            prior = log_prior(entry.popularity, max_popularity[entry.entity_type])
        doc = SearchDoc(
            EntityType(entry.entity_type),
            entry.entity_id,
            entry.name,
            _subtitle(entry),
            prior,
            artist_ids=entry.artist_ids,
        )
        index.add(doc, [entry.name], entry.aliases)
    return index.freeze()


def load_read_model(engine: Engine) -> ReadModel:
    """Builds the read model from the database.

    Raises:
        EmptyCatalogError: The catalog has never been ingested successfully.
    """
    started = time.perf_counter()
    with session_scope(engine) as session:
        version = catalog_version(session)
        if version is None:
            raise EmptyCatalogError("no successful ingestion run; run `songnexus ingest`")
        facts = read_catalog_facts(session)
        entries = read_search_entries(session)
    graph = build_graph(facts, version)
    search = build_search_index(entries, graph)
    log.info(
        "read model built",
        extra={
            "version": version,
            **graph.stats(),
            "searchDocs": len(search),
            "elapsedMs": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return ReadModel(version, graph, search)


def probe_version(engine: Engine) -> str | None:
    """Returns the current catalog version in the database (cheap)."""
    with session_scope(engine) as session:
        return catalog_version(session)


class ReadModelHolder:
    """Holds the current read model and swaps in a new one atomically.

    Requests call ``current()`` once and use that object for the whole request,
    so a reload mid-request never mixes two catalog versions.
    """

    def __init__(
        self,
        loader: Callable[[], ReadModel],
        version_probe: Callable[[], str | None],
    ) -> None:
        self._loader = loader
        self._probe = version_probe
        self._model: ReadModel | None = None
        self._reload_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        """True once a read model has loaded."""
        return self._model is not None

    def current(self) -> ReadModel:
        """Returns the current read model.

        Raises:
            ApiError: UNAVAILABLE when no catalog has been loaded yet.
        """
        model = self._model
        if model is None:
            raise ApiError(
                Status.UNAVAILABLE,
                "The catalog is not loaded yet; retry shortly.",
                reason="CATALOG_UNAVAILABLE",
                headers={"Retry-After": "5"},
            )
        return model

    def refresh(self) -> bool:
        """Loads a new read model if the catalog version changed. Returns whether it did.

        Concurrent callers do not rebuild twice; a failed load keeps serving the
        previous model.
        """
        if not self._reload_lock.acquire(blocking=False):
            return False
        try:
            version = self._probe()
            if version is None or (self._model is not None and self._model.version == version):
                return False
            self._model = self._loader()
            return True
        except Exception:
            log.exception("read model reload failed; serving the previous version")
            return False
        finally:
            self._reload_lock.release()
