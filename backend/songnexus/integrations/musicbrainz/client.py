"""Polite, resumable MusicBrainz HTTP client.

* Enforces the documented 1 request/second limit (configurable interval).
* Retries 503/429/5xx and connection errors with exponential backoff,
  honouring Retry-After.
* Caches every successful response on disk keyed by request identity, so an
  interrupted fetch resumes without re-downloading and re-runs are free.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from songnexus import __version__
from songnexus.integrations.musicbrainz.snapshot import RawRecord, request_key

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class MusicBrainzError(RuntimeError):
    pass


class MusicBrainzClient:
    def __init__(
        self,
        base_url: str,
        cache_dir: Path,
        contact: str = "",
        min_interval_s: float = 1.1,
        max_retries: int = 5,
        http: httpx.Client | None = None,
    ) -> None:
        contact_part = f"; {contact}" if contact else ""
        self._base_url = base_url.rstrip("/")
        self._cache_dir = cache_dir
        self._min_interval_s = min_interval_s
        self._max_retries = max_retries
        self._last_request_at = 0.0
        self._http = http or httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={
                "User-Agent": f"SongNexus/{__version__} (UW-Madison CS620 capstone{contact_part})",
                "Accept": "application/json",
            },
        )
        self.network_requests = 0
        self.cache_hits = 0
        # Every record served during this client's lifetime, cached or fresh.
        # A snapshot is built from these so stale cache entries never leak in.
        self.session_records: dict[str, RawRecord] = {}

    def get(self, kind: str, path: str, params: dict[str, str | int]) -> RawRecord:
        key = request_key(path, params)
        cached = self._read_cache(key)
        if cached is not None:
            self.cache_hits += 1
            self.session_records[key] = cached
            return cached

        url = f"{self._base_url}/{path}"
        body = self._fetch_with_retries(url, {**params, "fmt": "json"})
        record = RawRecord(
            kind=kind,
            request_key=key,
            url=str(httpx.URL(url, params={**params, "fmt": "json"})),
            retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"),
            body=body,
        )
        self._write_cache(record)
        self.session_records[key] = record
        return record

    def _fetch_with_retries(self, url: str, params: dict[str, str | int]) -> dict[str, Any]:
        delay = 2.0
        for attempt in range(1, self._max_retries + 1):
            self._throttle()
            try:
                response = self._http.get(url, params=params)
                self.network_requests += 1
            except httpx.TransportError as exc:
                log.warning("musicbrainz transport error", extra={"url": url, "attempt": attempt, "error": str(exc)})
            else:
                if response.status_code == 200:
                    payload: dict[str, Any] = response.json()
                    return payload
                if response.status_code not in RETRYABLE_STATUS:
                    raise MusicBrainzError(f"GET {url} -> {response.status_code}: {response.text[:200]}")
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = max(delay, float(retry_after))
                log.warning(
                    "musicbrainz retryable status",
                    extra={"url": url, "status": response.status_code, "attempt": attempt},
                )
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
        raise MusicBrainzError(f"GET {url} failed after {self._max_retries} attempts")

    def _throttle(self) -> None:
        wait = self._min_interval_s - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _cache_path(self, key: str) -> Path:
        return self._cache_dir / f"{hashlib.sha1(key.encode()).hexdigest()}.json"

    def _read_cache(self, key: str) -> RawRecord | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        return RawRecord.from_json(path.read_text(encoding="utf-8"))

    def _write_cache(self, record: RawRecord) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._cache_path(record.request_key).with_suffix(".tmp")
        tmp.write_text(record.to_json(), encoding="utf-8")
        tmp.replace(self._cache_path(record.request_key))  # atomic on POSIX and Windows
