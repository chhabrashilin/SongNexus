"""Raw response records and the snapshot file that bundles them.

A snapshot is the unit of reproducibility: ingestion reads *only* from a
snapshot, never from the network, so the same snapshot always yields the same
canonical graph. Each record keeps enough metadata (URL, retrieval time,
content hash) to serve as provenance for every fact derived from it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


@dataclass(frozen=True)
class RawRecord:
    kind: str  # artist_search | artist | release_groups | releases | release
    request_key: str  # stable identity of the request, e.g. "artist/<mbid>?inc=..."
    url: str
    retrieved_at: str  # ISO-8601 UTC
    body: dict[str, Any]

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(self.body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> RawRecord:
        data = json.loads(line)
        return cls(
            kind=data["kind"],
            request_key=data["request_key"],
            url=data["url"],
            retrieved_at=data["retrieved_at"],
            body=data["body"],
        )


def request_key(path: str, params: dict[str, str | int]) -> str:
    """Canonical request identity: path plus sorted query params (minus fmt)."""
    filtered = {k: v for k, v in params.items() if k != "fmt"}
    query = urlencode(sorted(filtered.items()))
    return f"{path}?{query}" if query else path


def write_snapshot(records: Iterable[RawRecord], path: Path) -> int:
    """Write records sorted by request key so identical inputs give identical files."""
    ordered = sorted(records, key=lambda r: r.request_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 makes the gzip header deterministic as well.
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        for record in ordered:
            gz.write((record.to_json() + "\n").encode("utf-8"))
    return len(ordered)


def read_snapshot(path: Path) -> Iterator[RawRecord]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                yield RawRecord.from_json(line)
            except (KeyError, json.JSONDecodeError) as exc:
                raise ValueError(f"{path}:{line_no}: malformed snapshot record: {exc}") from exc
