"""A response cache for the expensive anonymous catalog reads.

Catalog answers depend only on the request and the catalog version, so a
serialized response is reusable by everyone until the read model refreshes.
Keys therefore always contain the ``graphVersion``: a refresh makes every old
entry unreachable (they age out by TTL and LRU), with no invalidation step.

Layers:

* an in-process TTL + LRU store, bounded by entry count and approximate bytes;
* an optional shared Redis store (``SONGNEXUS_REDIS_URL``) behind it, so several
  instances share work. If Redis is unreachable, the cache logs once and keeps
  serving from memory; it re-tries Redis after a short pause.

Concurrent misses for one key are coalesced (single-flight): ten requests for
the same path compute once. Only anonymous responses are ever stored; callers
pass personalized requests straight through (see ``cached_json``).
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol

from fastapi import Request, Response
from pydantic import BaseModel

from songnexus.service.routes.common import set_cache_control

log = logging.getLogger(__name__)

DEFAULT_TTL_S = 3600.0
DEFAULT_MAX_ENTRIES = 4096
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
# One response never takes more than this share of the byte budget.
MAX_ITEM_SHARE = 8
REMOTE_RETRY_S = 30.0
REMOTE_TIMEOUT_S = 0.25


class RemoteStore(Protocol):
    """The slice of a Redis client the cache uses (redis-py's names)."""

    def get(self, name: str) -> bytes | None:
        """Returns the stored value or None."""

    def set(self, name: str, value: bytes, ex: int | None = None) -> Any:
        """Stores a value that expires after ``ex`` seconds."""


class MemoryStore:
    """A thread-safe TTL + LRU store bounded by entries and approximate bytes."""

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_bytes: int = DEFAULT_MAX_BYTES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key: str) -> bytes | None:
        """Returns a live value and marks it recently used."""
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            expires, value = entry
            if expires <= self._clock():
                self._drop(key)
                return None
            self._items.move_to_end(key)
            return value

    def set(self, key: str, value: bytes, ttl_s: float) -> bool:
        """Stores a value; returns False when it is too large to keep."""
        size = len(value) + len(key)
        if size > self._max_bytes // MAX_ITEM_SHARE:
            return False
        with self._lock:
            if key in self._items:
                self._drop(key)
            self._items[key] = (self._clock() + ttl_s, value)
            self._bytes += size
            while self._items and (
                len(self._items) > self._max_entries or self._bytes > self._max_bytes
            ):
                self._drop(next(iter(self._items)))
        return True

    def _drop(self, key: str) -> None:
        _, value = self._items.pop(key)
        self._bytes -= len(value) + len(key)

    def __len__(self) -> int:
        return len(self._items)

    @property
    def size_bytes(self) -> int:
        """Approximate bytes held (keys plus values)."""
        return self._bytes


@dataclass
class _Flight:
    """One in-progress computation that concurrent callers wait on."""

    done: threading.Event
    value: bytes | None = None
    error: BaseException | None = None


@dataclass(frozen=True)
class Lookup:
    """A cache answer: the bytes and where they came from (``hit``, ``shared``, ``miss``)."""

    value: bytes
    source: str


class ResponseCache:
    """The response cache: memory first, optional Redis behind it, single-flight misses."""

    def __init__(
        self,
        *,
        ttl_s: float = DEFAULT_TTL_S,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_bytes: int = DEFAULT_MAX_BYTES,
        remote: RemoteStore | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._memory = MemoryStore(max_entries=max_entries, max_bytes=max_bytes, clock=clock)
        self._remote = remote
        self._clock = clock
        self._remote_retry_at = 0.0
        self._remote_warned = False
        self._flights: dict[str, _Flight] = {}
        self._lock = threading.Lock()
        self._counts = {"hits": 0, "misses": 0, "coalesced": 0, "remote_hits": 0}

    def get_or_compute(
        self, key: str, compute: Callable[[], bytes], *, ttl_s: float | None = None
    ) -> Lookup:
        """Returns the cached bytes for ``key``, computing them once on a miss.

        Errors raised by ``compute`` propagate to every caller waiting on that
        computation and are never stored.
        """
        value = self._memory.get(key)
        if value is not None:
            self._count("hits")
            return Lookup(value, "hit")
        value = self._remote_get(key)
        if value is not None:
            self._memory.set(key, value, ttl_s or self._ttl_s)
            self._count("hits")
            self._count("remote_hits")
            return Lookup(value, "hit")

        with self._lock:
            flight = self._flights.get(key)
            leader = flight is None
            if flight is None:
                flight = self._flights[key] = _Flight(threading.Event())
        if not leader:
            flight.done.wait()
            if flight.error is not None:
                raise flight.error
            assert flight.value is not None
            self._count("coalesced")
            return Lookup(flight.value, "shared")

        try:
            # A leader that arrived just after another finished re-checks first.
            value = self._memory.get(key)
            if value is None:
                self._count("misses")
                value = compute()
                ttl = ttl_s or self._ttl_s
                self._memory.set(key, value, ttl)
                self._remote_set(key, value, ttl)
                source = "miss"
            else:
                source = "hit"
            flight.value = value
            return Lookup(value, source)
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._flights.pop(key, None)
            flight.done.set()

    def stats(self) -> dict[str, int]:
        """Counters and sizes, for operations."""
        return {
            **self._counts,
            "entries": len(self._memory),
            "bytes": self._memory.size_bytes,
            "remote": int(self._remote is not None and self._remote_retry_at <= self._clock()),
        }

    def _count(self, name: str) -> None:
        with self._lock:
            self._counts[name] += 1

    def _remote_ready(self) -> bool:
        return self._remote is not None and self._clock() >= self._remote_retry_at

    def _remote_failed(self, exc: Exception) -> None:
        self._remote_retry_at = self._clock() + REMOTE_RETRY_S
        if not self._remote_warned:
            self._remote_warned = True
            log.warning(
                "redis unavailable (%s); serving from memory and retrying every %ds",
                type(exc).__name__,
                int(REMOTE_RETRY_S),
            )

    def _remote_get(self, key: str) -> bytes | None:
        if not self._remote_ready():
            return None
        assert self._remote is not None
        try:
            value = self._remote.get(key)
        except Exception as exc:  # any client or network failure means "serve from memory"
            self._remote_failed(exc)
            return None
        return value if isinstance(value, bytes) else None

    def _remote_set(self, key: str, value: bytes, ttl_s: float) -> None:
        if not self._remote_ready() or len(value) > DEFAULT_MAX_BYTES // MAX_ITEM_SHARE:
            return
        assert self._remote is not None
        try:
            self._remote.set(key, value, ex=max(1, int(ttl_s)))
        except Exception as exc:  # see _remote_get
            self._remote_failed(exc)


def redis_store(url: str) -> RemoteStore | None:
    """Connects a Redis client (short timeouts, so a dead server never adds lag).

    Returns None, after logging once, when redis-py is missing or the server
    does not answer; the cache then runs on memory alone.
    """
    try:
        client = import_module("redis").Redis.from_url(
            url, socket_timeout=REMOTE_TIMEOUT_S, socket_connect_timeout=REMOTE_TIMEOUT_S
        )
        client.ping()
    except Exception as exc:  # ImportError, connection or URL errors alike
        log.warning("redis cache disabled (%s); using memory only", type(exc).__name__)
        return None
    log.info("response cache is backed by redis")
    store: RemoteStore = client
    return store


def build_cache(redis_url: str = "") -> ResponseCache:
    """Creates the process cache; Redis-backed when a URL is configured and reachable."""
    if not redis_url:
        return ResponseCache()
    remote = redis_store(redis_url)
    if remote is None:
        # Keep trying later: the server may simply not be up yet.
        return ResponseCache()
    return ResponseCache(remote=remote)


def cache_key(version: str, request: Request) -> str:
    """The key for one request: catalog version, path and every query parameter.

    Query parameters are sorted, so ordering never splits entries, and every
    parameter (filters, genres, modes, page tokens) is part of the key.
    """
    params = sorted(request.query_params.multi_items())
    digest = hashlib.sha256(
        json.dumps([request.url.path, params], separators=(",", ":")).encode()
    ).hexdigest()[:32]
    return f"sn:v1:{version}:{digest}"


def cached_anonymous[**P](func: Callable[P, BaseModel]) -> Callable[P, Any]:
    """Serves a catalog handler from the response cache for anonymous viewers.

    The handler must take keyword parameters ``request`` and ``model`` (the read
    model); an optional ``who`` (the viewer) decides sharing. A personalized
    viewer gets the handler's own, uncached result, and FastAPI serializes and
    labels it as before (``private, no-store``). Everyone else gets the cached
    JSON bytes, with the same public Cache-Control the handler sets.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
        request: Request = kwargs["request"]  # type: ignore[assignment]
        cache: ResponseCache | None = getattr(request.app.state, "response_cache", None)
        who = kwargs.get("who")
        if cache is None or bool(getattr(who, "personalized", False)):
            return func(*args, **kwargs)
        version: str = kwargs["model"].version  # type: ignore[attr-defined]

        def render() -> bytes:
            return func(*args, **kwargs).model_dump_json(by_alias=True).encode()

        found = cache.get_or_compute(cache_key(version, request), render)
        response = Response(found.value, media_type="application/json")
        set_cache_control(response, None)
        response.headers["X-Cache"] = found.source
        return response

    return wrapper
