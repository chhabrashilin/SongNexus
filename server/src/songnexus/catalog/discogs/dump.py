"""Download a Discogs masters dump, verify it, and extract our artists' masters.

The dump is about 600 MB compressed and 2.6 million masters; extraction streams
it once (about 17 minutes on a laptop) and keeps only masters whose main artists
are catalog artists. The result is a small snapshot that is committed, so
ingestion never needs the dump.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import re
import xml.etree.ElementTree as ET  # types only; parsing goes through defusedxml
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from defusedxml import ElementTree as SafeET

from songnexus.catalog.http import user_agent
from songnexus.catalog.snapshot import RawRecord, write_snapshot

log = logging.getLogger(__name__)

_DUMP_DATE = re.compile(r"^\d{8}$")
_MASTER_END = "</master>"
_READ_CHUNK = 1 << 20


class DumpError(RuntimeError):
    """The dump could not be downloaded or failed verification."""


def dump_file_name(dump_date: str, kind: str) -> str:
    """Returns e.g. ``discogs_20261001_masters.xml.gz``."""
    if not _DUMP_DATE.match(dump_date):
        raise ValueError(f"dump date must be YYYYMMDD, got {dump_date!r}")
    suffix = "CHECKSUM.txt" if kind == "CHECKSUM" else f"{kind}.xml.gz"
    return f"discogs_{dump_date}_{suffix}"


def download_url(dumps_url: str, dump_date: str, kind: str) -> str:
    """Returns the public download URL of one dump file."""
    key = f"data/{dump_date[:4]}/{dump_file_name(dump_date, kind)}"
    return f"{dumps_url.rstrip('/')}/?download={quote(key, safe='')}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(_READ_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(http: httpx.Client, url: str, target: Path) -> None:
    partial = target.with_suffix(target.suffix + ".part")
    with http.stream("GET", url, follow_redirects=True) as response:
        if response.status_code != httpx.codes.OK:
            raise DumpError(f"GET {url} -> {response.status_code}")
        with partial.open("wb") as fh:
            for block in response.iter_bytes(_READ_CHUNK):
                fh.write(block)
    partial.replace(target)


def fetch_masters_dump(
    dumps_url: str,
    dump_date: str,
    cache_dir: Path,
    *,
    contact: str = "",
    http: httpx.Client | None = None,
) -> tuple[Path, str]:
    """Returns the local masters dump and its SHA-256, downloading it if needed.

    The file is verified against Discogs' published checksum file every time,
    including when it is already cached.

    Raises:
        DumpError: A download failed or the checksum does not match.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    client = http or httpx.Client(
        timeout=httpx.Timeout(120.0, connect=10.0), headers={"User-Agent": user_agent(contact)}
    )
    checksum_path = cache_dir / dump_file_name(dump_date, "CHECKSUM")
    dump_path = cache_dir / dump_file_name(dump_date, "masters")
    if not checksum_path.exists():
        _download(client, download_url(dumps_url, dump_date, "CHECKSUM"), checksum_path)
    expected = {
        name.lstrip("*"): digest
        for digest, name in (
            line.split() for line in checksum_path.read_text().splitlines() if line.strip()
        )
    }.get(dump_path.name)
    if expected is None:
        raise DumpError(f"{checksum_path.name} has no entry for {dump_path.name}")
    if not dump_path.exists():
        log.info("downloading discogs dump", extra={"file": dump_path.name})
        _download(client, download_url(dumps_url, dump_date, "masters"), dump_path)
    actual = _sha256(dump_path)
    if actual != expected:
        raise DumpError(
            f"{dump_path.name}: sha256 {actual} does not match the published {expected}"
        )
    return dump_path, actual


def iter_masters(path: Path) -> Iterator[ET.Element]:
    """Yields each ``<master>`` element of a masters dump.

    Each master is parsed on its own rather than with one streaming parser over
    the whole file: expat's allocation tracking (expat >= 2.7) rejects a
    single multi-gigabyte document as "out of memory" even when elements are
    cleared as they are read. Master text never contains a literal
    ``</master>`` (markup is escaped), so splitting on it is exact.
    """
    buffer = ""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        while chunk := fh.read(_READ_CHUNK):
            buffer += chunk
            *complete, buffer = buffer.split(_MASTER_END)
            for piece in complete:
                start = piece.find("<master ")
                if start >= 0:
                    # The dump is third-party input: entity expansion and DTDs are refused.
                    yield SafeET.fromstring(piece[start:] + _MASTER_END)


def master_facts(master: ET.Element) -> dict[str, Any]:
    """Returns the fields SongNexus uses from one master, verbatim."""
    year = master.findtext("year") or ""
    return {
        "id": master.get("id", ""),
        "title": master.findtext("title") or "",
        "year": int(year) if year.isdigit() and year != "0" else None,
        "mainArtists": sorted(
            {a.findtext("id") or "" for a in master.iterfind("artists/artist")} - {""}
        ),
        "genres": [g.text for g in master.iterfind("genres/genre") if g.text],
        "styles": [s.text for s in master.iterfind("styles/style") if s.text],
    }


def extract_artist_masters(
    masters: Iterable[ET.Element], discogs_artist_ids: Iterable[str]
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """Groups the masters of the wanted artists by artist ID.

    Returns:
        (artist ID -> masters sorted by ID, number of masters scanned).
    """
    wanted = set(discogs_artist_ids)
    by_artist: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scanned = 0
    for master in masters:
        scanned += 1
        artists = {a.findtext("id") or "" for a in master.iterfind("artists/artist")}
        mine = artists & wanted
        if mine:
            facts = master_facts(master)
            for artist_id in mine:
                by_artist[artist_id].append(facts)
    for items in by_artist.values():
        items.sort(key=lambda f: int(f["id"]) if f["id"].isdigit() else 0)
    return dict(by_artist), scanned


def snapshot_records(
    by_artist: dict[str, list[dict[str, Any]]],
    *,
    dumps_url: str,
    dump_date: str,
    sha256: str,
    scanned: int,
) -> list[RawRecord]:
    """Returns the snapshot records: one manifest plus one record per artist.

    ``retrieved_at`` is the dump's publication date, so the same dump always
    yields the same snapshot bytes.
    """
    published = f"{dump_date[:4]}-{dump_date[4:6]}-{dump_date[6:]}T00:00:00+00:00"
    url = download_url(dumps_url, dump_date, "masters")
    records = [
        RawRecord(
            kind="dump_manifest",
            request_key=f"dump/{dump_date}/masters",
            url=url,
            retrieved_at=published,
            body={
                "file": dump_file_name(dump_date, "masters"),
                "sha256": sha256,
                "mastersScanned": scanned,
            },
        )
    ]
    for artist_id, masters in sorted(by_artist.items(), key=lambda kv: int(kv[0])):
        records.append(
            RawRecord(
                kind="masters",
                request_key=f"dump/{dump_date}/masters?artist={artist_id}",
                url=url,
                retrieved_at=published,
                body={"artist": artist_id, "masters": masters},
            )
        )
    return records


def run_extract(
    dump_path: Path,
    *,
    sha256: str,
    dumps_url: str,
    dump_date: str,
    discogs_artist_ids: Iterable[str],
    snapshot_path: Path,
) -> dict[str, Any]:
    """Extracts the wanted artists' masters from a verified dump into a snapshot."""
    wanted = set(discogs_artist_ids)
    by_artist, scanned = extract_artist_masters(iter_masters(dump_path), wanted)
    records = snapshot_records(
        by_artist, dumps_url=dumps_url, dump_date=dump_date, sha256=sha256, scanned=scanned
    )
    written = write_snapshot(records, snapshot_path)
    stats = {
        "dump": dump_file_name(dump_date, "masters"),
        "mastersScanned": scanned,
        "artistsWanted": len(wanted),
        "artistsWithMasters": len(by_artist),
        "masters": sum(len(v) for v in by_artist.values()),
        "records": written,
    }
    log.info("discogs extract finished", extra=stats)
    return stats
