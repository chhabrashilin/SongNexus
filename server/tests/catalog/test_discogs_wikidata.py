"""Fetching enrichment data: the Discogs dump extract and the Wikidata queries (no network)."""

import gzip
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from songnexus.catalog.discogs import dump
from songnexus.catalog.musicbrainz.client import MusicBrainzClient
from songnexus.catalog.musicbrainz.fetch import fetch_genre_list
from songnexus.catalog.snapshot import read_snapshot
from songnexus.catalog.wikidata import fetch as wikidata

MASTERS_XML = (
    "<masters>\n"
    '<master id="10"><main_release>1</main_release>'
    "<artists><artist><id>101</id><name>Alice</name></artist></artists>"
    "<genres><genre>Hip Hop</genre></genres><styles><style>Trap</style></styles>"
    "<year>2001</year><title>One &amp; Only</title>"
    "<videos><video><description>line one\n"
    "line two with a &lt;/master&gt; lookalike</description></video></videos></master>\n"
    '<master id="11"><artists><artist><id>999</id><name>Someone else</name></artist></artists>'
    "<genres><genre>Rock</genre></genres><year>0</year><title>Not ours</title></master>\n"
    '<master id="12"><artists><artist><id>101</id></artist><artist><id>201</id></artist>'
    "</artists><genres><genre>Jazz</genre></genres><title>Together</title></master>\n"
    "</masters>\n"
)


def _write_dump(tmp_path: Path, xml: str = MASTERS_XML) -> Path:
    path = tmp_path / "discogs_20261001_masters.xml.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(xml)
    return path


def test_masters_are_split_exactly_even_across_lines(tmp_path: Path) -> None:
    masters = list(dump.iter_masters(_write_dump(tmp_path)))
    assert [m.get("id") for m in masters] == ["10", "11", "12"]
    facts = dump.master_facts(masters[0])
    assert facts == {
        "id": "10",
        "title": "One & Only",
        "year": 2001,
        "mainArtists": ["101"],
        "genres": ["Hip Hop"],
        "styles": ["Trap"],
    }
    assert dump.master_facts(masters[1])["year"] is None  # Discogs writes 0 for unknown


def test_entities_defined_in_the_dump_never_expand(tmp_path: Path) -> None:
    # Each master is parsed alone, so a DTD anywhere in the file never reaches the
    # parser; a reference to its entity is an undefined-entity error, not an expansion.
    hostile = (
        '<!DOCTYPE masters [<!ENTITY boom "aaaaaaaaaa">]>'
        '<masters><master id="1"><title>&boom;</title></master></masters>'
    )
    with pytest.raises(ET.ParseError, match="undefined entity"):
        list(dump.iter_masters(_write_dump(tmp_path, hostile)))


def test_extract_keeps_only_wanted_artists_and_is_deterministic(tmp_path: Path) -> None:
    path = _write_dump(tmp_path)
    by_artist, scanned = dump.extract_artist_masters(dump.iter_masters(path), {"101", "201"})
    assert scanned == 3
    assert [m["id"] for m in by_artist["101"]] == ["10", "12"]
    assert [m["id"] for m in by_artist["201"]] == ["12"]

    out = tmp_path / "snap.jsonl.gz"
    stats = dump.run_extract(
        path,
        sha256="abc",
        dumps_url="https://data.discogs.test/",
        dump_date="20261001",
        discogs_artist_ids=["101", "201"],
        snapshot_path=out,
    )
    assert stats["artistsWithMasters"] == 2
    records = list(read_snapshot(out))
    assert [r.kind for r in records] == ["dump_manifest", "masters", "masters"]
    assert records[0].body["sha256"] == "abc"
    assert all(r.retrieved_at == "2026-10-01T00:00:00+00:00" for r in records)
    first_bytes = out.read_bytes()
    dump.run_extract(
        path,
        sha256="abc",
        dumps_url="https://data.discogs.test/",
        dump_date="20261001",
        discogs_artist_ids=["201", "101"],
        snapshot_path=out,
    )
    assert out.read_bytes() == first_bytes


def _dump_server(content: bytes, published_sha: str) -> httpx.Client:
    checksum = f"{published_sha} discogs_20261001_masters.xml.gz\n".encode()

    def handler(request: httpx.Request) -> httpx.Response:
        key = parse_qs(request.url.query.decode())["download"][0]
        return httpx.Response(200, content=checksum if key.endswith("CHECKSUM.txt") else content)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_the_dump_is_verified_against_the_published_checksum(tmp_path: Path) -> None:
    content = b"not really gzip"
    good = hashlib.sha256(content).hexdigest()
    path, sha = dump.fetch_masters_dump(
        "https://data.discogs.test/", "20261001", tmp_path / "a", http=_dump_server(content, good)
    )
    assert sha == good
    assert path.read_bytes() == content
    with pytest.raises(dump.DumpError, match="does not match"):
        dump.fetch_masters_dump(
            "https://data.discogs.test/",
            "20261001",
            tmp_path / "b",
            http=_dump_server(content, "0" * 64),
        )


def test_dump_dates_are_validated() -> None:
    assert dump.download_url("https://data.discogs.com/", "20261001", "masters") == (
        "https://data.discogs.com/?download=data%2F2026%2Fdiscogs_20261001_masters.xml.gz"
    )
    with pytest.raises(ValueError, match="YYYYMMDD"):
        dump.dump_file_name("2026-10-01", "masters")


def test_wikidata_queries_are_batched_posted_and_cached(tmp_path: Path) -> None:
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        query = parse_qs(request.content.decode())["query"][0]
        queries.append(query)
        rows: list[dict[str, Any]] = []
        if "P1953" in query:
            rows = [{"musicbrainz": {"value": "mb-1"}, "discogs": {"value": "7"}}]
        else:
            rows = [{"genre": {"value": "g-trap"}, "parent": {"value": "g-hiphop"}}]
        return httpx.Response(200, json={"results": {"bindings": rows}})

    def client() -> wikidata.WikidataClient:
        return wikidata.WikidataClient(
            sparql_url="https://query.wikidata.test/sparql",
            cache_dir=tmp_path / "cache",
            min_interval_s=0,
            http=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    mbids = [f"mb-{i}" for i in range(wikidata.ARTIST_BATCH + 1)]
    stats = wikidata.run_fetch(
        client(), musicbrainz_artist_ids=mbids, snapshot_path=tmp_path / "wd.jsonl.gz"
    )
    assert len(queries) == 3  # two artist batches and the hierarchy
    assert stats["artistsWithDiscogs"] == 1
    assert stats["genreParentLinks"] == 1
    again = wikidata.run_fetch(
        client(), musicbrainz_artist_ids=mbids, snapshot_path=tmp_path / "wd.jsonl.gz"
    )
    assert len(queries) == 3  # all from cache
    assert again["cacheHits"] == 3


def test_the_genre_list_is_fetched_page_by_page(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        names = [f"genre {i}" for i in range(offset, min(offset + 100, 150))]
        return httpx.Response(
            200, json={"genre-count": 150, "genres": [{"id": n, "name": n} for n in names]}
        )

    client = MusicBrainzClient(
        base_url="https://musicbrainz.test/ws/2",
        cache_dir=tmp_path,
        min_interval_s=0,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert fetch_genre_list(client) == 150
    assert client.network_requests == 2
