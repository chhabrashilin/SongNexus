"""Raw response records and the snapshot file that bundles them.

A snapshot is the unit of reproducibility: ingestion reads only from a
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
    """One upstream response, exactly as received.

    Attributes:
        kind: What was requested: ``artist_search``, ``artist``, ``artist_profile``,
            ``release_groups``, ``releases`` or ``release``.
        request_key: Stable identity of the request (path plus sorted query).
        url: The full URL that was fetched.
        retrieved_at: ISO-8601 UTC retrieval time.
        body: The decoded JSON response.
    """

    kind: str
    request_key: str
    url: str
    retrieved_at: str
    body: dict[str, Any]

    @property
    def content_hash(self) -> str:
        """SHA-256 of the canonical JSON body; changes iff the content changes."""
        canonical = json.dumps(self.body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def to_json(self) -> str:
        """Serializes the record as one deterministic JSON line."""
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> RawRecord:
        """Parses a record serialized by ``to_json``.

        Raises:
            KeyError: A required field is missing.
            json.JSONDecodeError: The line is not JSON.
        """
        data = json.loads(line)
        return cls(
            kind=data["kind"],
            request_key=data["request_key"],
            url=data["url"],
            retrieved_at=data["retrieved_at"],
            body=data["body"],
        )


def request_key(path: str, params: dict[str, str | int]) -> str:
    """Returns the canonical request identity: path plus sorted params, minus ``fmt``."""
    filtered = {k: v for k, v in params.items() if k != "fmt"}
    query = urlencode(sorted(filtered.items()))
    return f"{path}?{query}" if query else path


def write_snapshot(records: Iterable[RawRecord], path: Path) -> int:
    """Writes records sorted by request key, so identical inputs give identical bytes.

    Returns:
        The number of records written.
    """
    ordered = sorted(records, key=lambda r: r.request_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    # An empty filename and mtime=0 keep the gzip header independent of where and
    # when the file was written.
    with (
        path.open("wb") as raw,
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz,
    ):
        for record in ordered:
            gz.write((record.to_json() + "\n").encode("utf-8"))
    return len(ordered)


def read_snapshot(path: Path) -> Iterator[RawRecord]:
    """Yields every record in a snapshot file.

    Raises:
        ValueError: A line is not a valid record; the message names the line.
    """
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                yield RawRecord.from_json(line)
            except (KeyError, json.JSONDecodeError) as exc:
                raise ValueError(f"{path}:{line_no}: malformed snapshot record: {exc}") from exc
