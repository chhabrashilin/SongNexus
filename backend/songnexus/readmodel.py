"""The read model: an immutable (graph, search index) pair built from the DB.

Queries run against a read model, never against half-updated state. After an
ingestion run, a new read model is built and swapped in atomically; caches live
on the read model, so the swap *is* the cache invalidation (no TTLs, no stale
paths). See docs/architecture.md#caching.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict, defaultdict
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import Engine, func, select

from songnexus.core.metrics import metrics
from songnexus.db import models as m
from songnexus.db.session import session_scope
from songnexus.graph.projection import DEFAULT_CATEGORIES, ArtistGraph, build_graph, kinds_for
from songnexus.search.index import SearchDoc, SearchIndex, log_prior

log = logging.getLogger(__name__)
T = TypeVar("T")


class LruCache:
    """Small thread-safe LRU with hit/miss metrics."""

    def __init__(self, name: str, capacity: int) -> None:
        self._name = name
        self._capacity = capacity
        self._data: OrderedDict[Hashable, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get_or_compute(self, key: Hashable, compute: Callable[[], T]) -> T:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                metrics.counter(f"cache.{self._name}.hit")
                return self._data[key]  # type: ignore[no-any-return]
        metrics.counter(f"cache.{self._name}.miss")
        value = compute()
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._capacity:
                self._data.popitem(last=False)
        return value


@dataclass
class ReadModel:
    version: str
    graph: ArtistGraph
    search: SearchIndex
    built_at: str
    build_ms: float
    path_cache: LruCache
    analytics_cache: LruCache
    track_artists: dict[str, list[str]] = field(default_factory=dict)


def _latest_run(engine: Engine) -> tuple[int | None, str | None]:
    with session_scope(engine) as session:
        row = session.execute(
            select(m.IngestionRun.id, m.IngestionRun.pipeline_version)
            .where(m.IngestionRun.status == "succeeded")
            .order_by(m.IngestionRun.id.desc())
            .limit(1)
        ).first()
    return (row[0], row[1]) if row else (None, None)


def build_read_model(engine: Engine, path_cache_size: int = 2048) -> ReadModel:
    started = time.perf_counter()
    run_id, pipeline_version = _latest_run(engine)
    version = f"run-{run_id}@{pipeline_version}" if run_id is not None else "empty"

    with session_scope(engine) as session:
        graph = build_graph(session, version)
        index = SearchIndex()

        aliases: dict[str, list[str]] = defaultdict(list)
        for artist_id, alias in session.execute(select(m.ArtistAlias.artist_id, m.ArtistAlias.alias)):
            aliases[artist_id].append(alias)

        default_adj = graph.adjacency(kinds_for(DEFAULT_CATEGORIES))
        max_degree = max((len(n) for n in default_adj.values()), default=0)
        for node in graph.nodes.values():
            degree_prior = log_prior(len(default_adj.get(node.id, {})), max_degree)
            parts = [p for p in (node.disambiguation, ", ".join(node.genres[:3])) if p]
            index.add(
                SearchDoc(
                    "artist",
                    node.id,
                    node.name,
                    subtitle=" · ".join(parts) or (node.artist_type or "Artist"),
                    prior=0.7 * degree_prior + (0.3 if node.hydrated else 0.0),
                ),
                names=[node.name],
                aliases=aliases.get(node.id, []),
            )

        track_artists: dict[str, list[str]] = defaultdict(list)
        credit_counts: dict[str, int] = defaultdict(int)
        for track_id, artist_id, role in session.execute(
            select(m.TrackCredit.track_id, m.TrackCredit.artist_id, m.TrackCredit.role).order_by(
                m.TrackCredit.track_id, m.TrackCredit.artist_id
            )
        ):
            credit_counts[track_id] += 1
            if role == "primary":
                track_artists[track_id].append(artist_id)
        max_credits = max(credit_counts.values(), default=0)
        for track_id, title in session.execute(select(m.Track.id, m.Track.title)):
            artists = ", ".join(graph.nodes[a].name for a in track_artists.get(track_id, []) if a in graph.nodes)
            index.add(
                SearchDoc(
                    "track",
                    track_id,
                    title,
                    subtitle=f"Track · {artists}",
                    prior=log_prior(credit_counts.get(track_id, 0), max_credits),
                ),
                names=[title],
            )

        album_artists: dict[str, list[str]] = defaultdict(list)
        for album_id, artist_id in session.execute(
            select(m.AlbumArtist.album_id, m.AlbumArtist.artist_id).order_by(m.AlbumArtist.position)
        ):
            album_artists[album_id].append(artist_id)
        for album_id, title, date in session.execute(select(m.Album.id, m.Album.title, m.Album.first_release_date)):
            artists = ", ".join(graph.nodes[a].name for a in album_artists.get(album_id, []) if a in graph.nodes)
            year = f" · {date[:4]}" if date else ""
            index.add(
                SearchDoc("album", album_id, title, subtitle=f"Album · {artists}{year}", prior=0.5), names=[title]
            )

    build_ms = round((time.perf_counter() - started) * 1000, 1)
    metrics.observe("readmodel.build_ms", build_ms)
    log.info("read model built", extra={"version": version, "build_ms": build_ms, "search_docs": len(index)})
    return ReadModel(
        version=version,
        graph=graph,
        search=index.freeze(),
        built_at=datetime.now(UTC).isoformat(timespec="seconds"),
        build_ms=build_ms,
        path_cache=LruCache("path", path_cache_size),
        analytics_cache=LruCache("analytics", 64),
        track_artists=dict(track_artists),
    )


class ReadModelStore:
    """Holds the current read model; ``reload`` swaps in a new one atomically."""

    def __init__(self, engine: Engine, path_cache_size: int = 2048) -> None:
        self._engine = engine
        self._path_cache_size = path_cache_size
        self._lock = threading.Lock()
        self._current: ReadModel | None = None
        self._listeners: list[Callable[[ReadModel], None]] = []

    def on_reload(self, listener: Callable[[ReadModel], None]) -> None:
        """Run ``listener(model)`` in a background thread after every reload."""
        self._listeners.append(listener)

    @property
    def current(self) -> ReadModel:
        model = self._current
        if model is None:
            model = self.reload()
        return model

    def reload(self) -> ReadModel:
        with self._lock:
            model = build_read_model(self._engine, self._path_cache_size)
            self._current = model
        for listener in self._listeners:
            threading.Thread(target=listener, args=(model,), name="readmodel-warmup", daemon=True).start()
        return model

    def count_rows(self) -> dict[str, int]:
        with session_scope(self._engine) as session:
            return {
                table.__tablename__: session.scalar(select(func.count()).select_from(table)) or 0
                for table in (m.Artist, m.Track, m.Album, m.TrackCredit, m.ArtistRelationship, m.RawRecord)
            }
