"""Unit tests for the response cache: TTL, LRU bounds, isolation, single-flight, Redis fallback."""

import threading
import time
from typing import Any

import pytest
from starlette.requests import Request

from songnexus.service.cache import MemoryStore, ResponseCache, cache_key


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def request(path: str, query: str = "") -> Request:
    return Request({"type": "http", "path": path, "query_string": query.encode(), "headers": []})


def test_entries_expire_after_their_ttl() -> None:
    clock = Clock()
    cache = ResponseCache(ttl_s=10, clock=clock)
    calls = []

    def compute() -> bytes:
        calls.append(1)
        return b"x"

    assert cache.get_or_compute("k", compute).source == "miss"
    assert cache.get_or_compute("k", compute).source == "hit"
    clock.now += 11
    assert cache.get_or_compute("k", compute).source == "miss"
    assert len(calls) == 2
    assert cache.stats()["hits"] == 1


def test_lru_bound_by_entries_evicts_the_least_recently_used() -> None:
    store = MemoryStore(max_entries=2)
    store.set("a", b"1", 60)
    store.set("b", b"2", 60)
    assert store.get("a") == b"1"  # a is now the most recent
    store.set("c", b"3", 60)
    assert store.get("b") is None
    assert store.get("a") == b"1"
    assert len(store) == 2


def test_lru_bound_by_bytes_and_oversized_items_are_skipped() -> None:
    store = MemoryStore(max_entries=100, max_bytes=800)
    assert store.set("big", b"x" * 500, 60) is False  # over one eighth of the budget
    for i in range(30):
        store.set(f"k{i}", b"y" * 90, 60)
    assert store.size_bytes <= 800
    assert store.get("k29") is not None
    assert store.get("k0") is None


def test_keys_are_isolated_by_version_and_every_parameter() -> None:
    path = "/v1/artists/a/connections"
    base = cache_key("v1", request(path, "pageSize=10&genres=x"))
    assert base == cache_key("v1", request(path, "genres=x&pageSize=10"))
    others = [
        cache_key("v2", request(path, "pageSize=10&genres=x")),
        cache_key("v1", request("/v1/artists/b/connections", "pageSize=10&genres=x")),
        cache_key("v1", request(path, "pageSize=10&genres=y")),
        cache_key("v1", request(path, "pageSize=10")),
        cache_key("v1", request(path, "pageSize=10&genres=x&pageToken=t")),
    ]
    assert len({base, *others}) == 6


def test_concurrent_misses_compute_once() -> None:
    cache = ResponseCache()
    calls = []
    release = threading.Event()

    def slow() -> bytes:
        calls.append(1)
        release.wait(5)
        return b"result"

    results: list[Any] = []
    threads = [
        threading.Thread(target=lambda: results.append(cache.get_or_compute("k", slow)))
        for _ in range(10)
    ]
    for t in threads:
        t.start()
    time.sleep(0.3)
    release.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 1
    assert [r.value for r in results] == [b"result"] * 10
    assert sorted(r.source for r in results).count("miss") == 1


def test_errors_are_never_stored() -> None:
    cache = ResponseCache()

    def boom() -> bytes:
        raise ValueError("no")

    with pytest.raises(ValueError, match="no"):
        cache.get_or_compute("k", boom)
    assert cache.get_or_compute("k", lambda: b"ok").source == "miss"


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.down = False
        self.calls = 0

    def get(self, name: str) -> bytes | None:
        self.calls += 1
        if self.down:
            raise ConnectionError("down")
        return self.data.get(name)

    def set(self, name: str, value: bytes, ex: int | None = None) -> bool:
        self.calls += 1
        if self.down:
            raise ConnectionError("down")
        self.data[name] = value
        return True


def test_redis_is_shared_between_instances() -> None:
    redis = FakeRedis()
    first, second = ResponseCache(remote=redis), ResponseCache(remote=redis)
    assert first.get_or_compute("k", lambda: b"v").source == "miss"
    found = second.get_or_compute("k", lambda: pytest.fail("should come from redis"))
    assert (found.value, found.source) == (b"v", "hit")
    assert second.stats()["remote_hits"] == 1


def test_redis_down_falls_back_to_memory_and_logs_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis, clock = FakeRedis(), Clock()
    redis.down = True
    cache = ResponseCache(remote=redis, clock=clock)
    with caplog.at_level("WARNING"):
        assert cache.get_or_compute("a", lambda: b"1").value == b"1"
        assert cache.get_or_compute("a", lambda: b"2").value == b"1"  # served from memory
        assert cache.get_or_compute("b", lambda: b"3").value == b"3"
    assert sum("redis unavailable" in r.message for r in caplog.records) == 1
    calls = redis.calls
    cache.get_or_compute("c", lambda: b"4")
    assert redis.calls == calls  # not retried inside the pause
    redis.down = False
    clock.now += 60
    cache.get_or_compute("d", lambda: b"5")
    assert redis.data.get("d") == b"5"
