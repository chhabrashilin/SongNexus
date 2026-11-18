"""The read model: the artist graph and search index for one catalog version.

Built once from the database after ingestion and shared read-only by every
request. A new catalog version builds a new read model; nothing mutates one.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from songnexus.core.graph.algorithms import weighted_degree
from songnexus.core.graph.model import DEFAULT_CATEGORIES, ArtistGraph, kinds_for
from songnexus.core.graph.projection import build_graph
from songnexus.core.links import parse_link
from songnexus.core.listening import MIN_LISTENERS
from songnexus.core.resolution import Resolution, resolve_batch
from songnexus.core.search import EntityType, SearchDoc, SearchIndex, log_prior
from songnexus.core.text import normalize
from songnexus.service.errors import ApiError, Status
from songnexus.storage import catalog_repository
from songnexus.storage.artist_images import images_stamp, read_artist_images
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


class ResolutionCache:
    """Name resolutions for one catalog version, shared by all requests (bounded LRU).

    Batch resolution costs a few milliseconds per distinct name; popular artists
    recur across playlists, so each is resolved once per catalog version.
    """

    def __init__(self, max_entries: int = 100_000) -> None:
        self._entries: OrderedDict[str, Resolution] = OrderedDict()
        self._max = max_entries
        self._lock = threading.Lock()

    def resolve(self, index: SearchIndex, names: Sequence[str]) -> list[Resolution]:
        """Resolves artist names, from the cache where possible, in input order."""
        keys = [normalize(name) for name in names]
        # Snapshot hits under the lock: another request may evict entries before
        # this one is done, so nothing below reads the shared map again.
        with self._lock:
            known: dict[str, Resolution] = {}
            for key in dict.fromkeys(keys):
                if key in self._entries:
                    self._entries.move_to_end(key)
                    known[key] = self._entries[key]
        missing = [k for k in dict.fromkeys(keys) if k not in known]
        known.update(zip(missing, resolve_batch(index, missing), strict=True))
        with self._lock:
            for key in missing:
                self._entries[key] = known[key]
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
        return [replace(known[key], mention=name) for name, key in zip(names, keys, strict=True)]


class Memo:
    """Values derived from one read model, computed once on first use (thread-safe)."""

    def __init__(self) -> None:
        self._values: dict[str, object] = {}
        self._lock = threading.Lock()

    def get[T](self, key: str, compute: Callable[[], T]) -> T:
        """Returns the cached value for ``key``, computing it under the lock once."""
        with self._lock:
            if key not in self._values:
                self._values[key] = compute()
            return self._values[key]  # type: ignore[return-value]


@dataclass(frozen=True)
class ReadModel:
    """Everything request handlers read, for one catalog version."""

    version: str
    graph: ArtistGraph
    search: SearchIndex
    resolutions: ResolutionCache = field(default_factory=ResolutionCache)
    # Link key (core.links) -> artist ID: the artist pages other apps link to, from the
    # links MusicBrainz stores. Shared links resolve here without any network call.
    artist_links: dict[str, str] = field(default_factory=dict)
    memo: Memo = field(default_factory=Memo)


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


def load_read_model(engine: Engine, genre_sources: Sequence[str] | None = None) -> ReadModel:
    """Builds the read model from the database.

    Args:
        engine: The catalog database.
        genre_sources: Which genre sources to use (``Settings.genre_sources``); all when None.

    Raises:
        EmptyCatalogError: The catalog has never been ingested successfully.
    """
    started = time.perf_counter()
    with session_scope(engine) as session:
        version = _version(session)
        if version is None:
            raise EmptyCatalogError("no successful ingestion run; run `songnexus ingest`")
        facts = read_catalog_facts(session, genre_sources)
        entries = read_search_entries(session)
        images = read_artist_images(session)
        listeners = catalog_repository.audience_listeners(session)
        link_rows = catalog_repository.artist_link_urls(session)
    graph = build_graph(facts, version)
    graph.images = {
        artist_id: image for artist_id, image in images.items() if artist_id in graph.nodes
    }
    # Below the floor an audience is not described anywhere (core.listening).
    graph.listeners = {
        artist_id: count
        for artist_id, count in listeners.items()
        if artist_id in graph.nodes and count >= MIN_LISTENERS
    }
    search = build_search_index(entries, graph)
    artist_links = link_index(link_rows, graph)
    log.info(
        "read model built",
        extra={
            "version": version,
            **graph.stats(),
            "searchDocs": len(search),
            "artistLinks": len(artist_links),
            "elapsedMs": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return ReadModel(version, graph, search, artist_links=artist_links)


def link_index(rows: Sequence[tuple[str, str]], graph: ArtistGraph) -> dict[str, str]:
    """Maps the key of every recognized artist link to its artist.

    A key shared by two artists (a label's channel, a mistaken link) is dropped:
    a shared link must never open the wrong artist.
    """
    index: dict[str, str] = {}
    ambiguous: set[str] = set()
    for artist_id, url in rows:
        link = parse_link(url)
        if link is None or artist_id not in graph.nodes:
            continue
        if index.setdefault(link.key, artist_id) != artist_id:
            ambiguous.add(link.key)
    for key in ambiguous:
        del index[key]
    return index


def _version(session: Session) -> str | None:
    """The served version: the catalog run, plus a stamp of the artist photos when any exist.

    Photos are fetched after ingestion (``songnexus fetch-images``), so they get
    their own stamp: a fetch that changes them reloads the read model and so
    changes every cache key and ETag, without a re-ingest.
    """
    version = catalog_version(session)
    stamp = images_stamp(session) if version is not None else None
    return f"{version}.img{stamp}" if stamp else version


def probe_version(engine: Engine) -> str | None:
    """Returns the current catalog version in the database (cheap)."""
    with session_scope(engine) as session:
        return _version(session)


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
