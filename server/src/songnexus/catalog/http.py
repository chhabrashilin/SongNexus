"""Polite, resumable HTTP client shared by the catalog sources.

* Enforces a minimum interval between requests (each source documents its own).
* Retries 429, 5xx and connection errors with exponential backoff, honoring
  ``Retry-After``.
* Caches every successful response on disk keyed by request identity, so an
  interrupted fetch resumes without re-downloading and re-runs are free.
* Identifies itself with a User-Agent naming the project and, when configured,
  a contact; never a personal address by default.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from songnexus import __version__
from songnexus.catalog.snapshot import RawRecord, request_key

log = logging.getLogger(__name__)

HTTP_OK = 200
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_BACKOFF_S = 60.0


class SourceRequestError(RuntimeError):
    """A request failed permanently (non-retryable status or retries exhausted)."""


def user_agent(contact: str = "") -> str:
    """Returns the User-Agent every source sees."""
    contact_part = f"; {contact}" if contact else ""
    return f"SongNexus/{__version__} (capstone research project{contact_part})"


class PoliteClient:
    """Fetches JSON responses from one source as ``RawRecord`` values."""

    error_type: type[SourceRequestError] = SourceRequestError

    def __init__(
        self,
        *,
        source: str,
        base_url: str,
        cache_dir: Path,
        contact: str = "",
        min_interval_s: float = 1.1,
        max_retries: int = 5,
        accept: str = "application/json",
        timeout_s: float = 60.0,
        remember: bool = True,
        http: httpx.Client | None = None,
    ) -> None:
        """Creates a client.

        Args:
            source: Source name for logs and errors (e.g. ``musicbrainz``).
            base_url: Root that request paths are relative to.
            cache_dir: Directory for the on-disk response cache.
            contact: Optional contact (URL or address) for the User-Agent.
            min_interval_s: Minimum seconds between network requests.
            max_retries: Attempts per request before giving up.
            accept: The Accept header.
            timeout_s: Read timeout per request.
            remember: Keep every record served in ``session_records`` (for building a
                snapshot from them). Off for large responses that callers digest as
                they arrive, which would otherwise all stay in memory.
            http: Injected HTTP client (tests use a mock transport).
        """
        self._source = source
        self._base_url = base_url.rstrip("/")
        self._cache_dir = cache_dir
        self._min_interval_s = min_interval_s
        self._max_retries = max_retries
        self._last_request_at = 0.0
        self._http = http or httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            headers={"User-Agent": user_agent(contact), "Accept": accept},
        )
        self._remember = remember
        self.network_requests = 0
        self.cache_hits = 0
        # Every record served during this client's lifetime, cached or fresh. A
        # snapshot is built from these, so stale cache entries never leak in.
        self.session_records: dict[str, RawRecord] = {}

    def get(self, kind: str, path: str, params: dict[str, str | int]) -> RawRecord:
        """Returns the response to a GET, from cache when available.

        Raises:
            SourceRequestError: The request failed permanently.
        """
        return self._request(kind, path, request_key(path, params), params=params)

    def cached_get(self, path: str, params: dict[str, str | int]) -> RawRecord | None:
        """Returns the cached response to a GET, or None, without touching the network."""
        return self._read_cache(request_key(path, params))

    def post_form(self, kind: str, path: str, form: dict[str, str]) -> RawRecord:
        """Returns the response to a form POST (long queries), from cache when available.

        The request key is the path plus a hash of the form, so keys stay short and
        an edited query is a new request.

        Raises:
            SourceRequestError: The request failed permanently.
        """
        digest = hashlib.sha256(repr(sorted(form.items())).encode()).hexdigest()[:32]
        return self._request(kind, path, f"{path}?form={digest}", form=form)

    def post_json(self, kind: str, path: str, payload: Any) -> RawRecord:
        """Returns the response to a JSON POST, from cache when available.

        The request key is the path plus a hash of the payload. A response that
        is a JSON list is stored as ``{"items": [...]}`` (records hold objects).

        Raises:
            SourceRequestError: The request failed permanently.
        """
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:32]
        return self._request(kind, path, f"{path}?json={digest}", json_body=payload)

    def _request(
        self,
        kind: str,
        path: str,
        key: str,
        *,
        params: dict[str, str | int] | None = None,
        form: dict[str, str] | None = None,
        json_body: Any = None,
    ) -> RawRecord:
        cached = self._read_cache(key)
        if cached is not None:
            self.cache_hits += 1
            if self._remember:
                self.session_records[key] = cached
            return cached

        url = f"{self._base_url}/{path}" if path else self._base_url
        full_params = self.extra_params() | (params or {})
        body = self._fetch_with_retries(url, full_params, form, json_body)
        record = RawRecord(
            kind=kind,
            request_key=key,
            url=str(httpx.URL(url, params=full_params)),
            retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"),
            body=body,
        )
        self._write_cache(record)
        if self._remember:
            self.session_records[key] = record
        return record

    def extra_params(self) -> dict[str, str | int]:
        """Query parameters added to every request (e.g. a response format)."""
        return {}

    def _fetch_with_retries(
        self,
        url: str,
        params: dict[str, str | int],
        form: dict[str, str] | None,
        json_body: Any = None,
    ) -> dict[str, Any]:
        method = "POST" if form is not None or json_body is not None else "GET"
        delay = 2.0
        for attempt in range(1, self._max_retries + 1):
            self._throttle()
            try:
                response = self._http.request(method, url, params=params, data=form, json=json_body)
                self.network_requests += 1
            except httpx.TransportError as exc:
                log.warning(
                    "%s transport error",
                    self._source,
                    extra={"url": url, "attempt": attempt, "error": str(exc)},
                )
            else:
                if response.status_code == HTTP_OK:
                    decoded = response.json()
                    payload: dict[str, Any] = (
                        decoded if isinstance(decoded, dict) else {"items": decoded}
                    )
                    return payload
                if response.status_code not in RETRYABLE_STATUS:
                    raise self.error_type(
                        f"{method} {url} -> {response.status_code}: {response.text[:200]}"
                    )
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = max(delay, float(retry_after))
                log.warning(
                    "%s retryable status",
                    self._source,
                    extra={"url": url, "status": response.status_code, "attempt": attempt},
                )
            if attempt < self._max_retries:
                time.sleep(delay)
                delay = min(delay * 2, _MAX_BACKOFF_S)
        raise self.error_type(f"{method} {url} failed after {self._max_retries} attempts")

    def _throttle(self) -> None:
        wait = self._min_interval_s - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _cache_path(self, key: str) -> Path:
        return self._cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    def _read_cache(self, key: str) -> RawRecord | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            record = RawRecord.from_json(path.read_text(encoding="utf-8"))
        except (KeyError, ValueError):
            # A torn or corrupt cache file (e.g. an interrupted disk write) is a miss.
            log.warning("ignoring corrupt cache entry", extra={"path": str(path)})
            return None
        return record if record.request_key == key else None

    def _write_cache(self, record: RawRecord) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        target = self._cache_path(record.request_key)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(record.to_json(), encoding="utf-8")
        tmp.replace(target)  # Atomic on POSIX and Windows.
