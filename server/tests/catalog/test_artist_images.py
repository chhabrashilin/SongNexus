"""Artist photos from Wikidata and Commons: parsing, license filtering, idempotent storage."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import Engine, select

from songnexus.catalog.ingest import ingest_snapshot
from songnexus.catalog.snapshot import write_snapshot
from songnexus.catalog.wikidata import images
from songnexus.catalog.wikidata.fetch import WikidataClient
from songnexus.core import ids
from songnexus.storage import migrate
from songnexus.storage import models as m
from songnexus.storage.db import make_engine, session_scope
from tests.catalog import fixtures as fx

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
ENTITY = "http://www.wikidata.org/entity/"
FILE_PATH = "http://commons.wikimedia.org/wiki/Special:FilePath/"


@pytest.mark.parametrize(
    ("name", "free"),
    [
        ("CC BY-SA 4.0", True),
        ("CC BY 2.0", True),
        ("CC BY-SA 3.0 de", True),
        ("CC BY-SA 2.0 igo", True),
        ("CC0", True),
        ("Public domain", True),
        ("PD-US", True),
        ("CC BY-NC 2.0", False),
        ("CC BY-NC-SA 4.0", False),
        ("CC BY-ND 3.0", False),
        ("GFDL", False),
        ("Fair use", False),
        ("", False),
    ],
)
def test_only_free_licenses_are_accepted(name: str, free: bool) -> None:
    assert images.is_free_license(name) is free


def test_file_titles_come_from_special_file_path_urls() -> None:
    assert images.file_title(f"{FILE_PATH}Bj%C3%B6rk%20at_Cannes.jpg") == "File:Björk at Cannes.jpg"
    assert images.file_title("http://example.org/not-a-file") is None


def test_author_html_is_reduced_to_text() -> None:
    raw = '<a href="https://www.flickr.com/people/x">Luan &amp; Co</a>\n <span>(Flickr)</span>'
    assert images.plain_text(raw) == "Luan & Co (Flickr)"


def test_sparql_rows_are_grouped_by_musicbrainz_id() -> None:
    rows = [
        {"musicbrainz": "a", "item": f"{ENTITY}Q1", "image": f"{FILE_PATH}B.jpg"},
        {"musicbrainz": "a", "item": f"{ENTITY}Q1", "image": f"{FILE_PATH}A.jpg"},
        {"musicbrainz": "b", "item": f"{ENTITY}Q2"},
    ]
    matches = images.parse_images(rows)
    assert matches["a"] == images.WikidataMatch(frozenset({"Q1"}), ("File:A.jpg", "File:B.jpg"))
    assert matches["b"] == images.WikidataMatch(frozenset({"Q2"}), ())


def _info(title: str, width: int, **overrides: Any) -> dict[str, Any]:
    stem = title.removeprefix("File:").replace(" ", "_")
    info: dict[str, Any] = {
        "url": f"https://upload.wikimedia.org/wikipedia/commons/a/aa/{stem}",
        "thumburl": f"https://thumb.wikimedia.org/wikipedia/commons/thumb/a/aa/{stem}/{width}px-{stem}",
        "descriptionurl": f"https://commons.wikimedia.org/wiki/{stem}",
        "width": 2000,
        "height": 3000,
        "mime": "image/jpeg",
        "extmetadata": {
            "Artist": {"value": '<a href="https://example.org">Jane Photographer</a>'},
            "LicenseShortName": {"value": "CC BY-SA 4.0"},
            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
            "AttributionRequired": {"value": "true"},
        },
    }
    info.update(overrides)
    return info


# File title -> imageinfo overrides; None means Commons has no such file.
COMMONS_FILES: dict[str, dict[str, Any] | None] = {
    "File:Alice.jpg": {},
    "File:Bob.jpg": {
        "extmetadata": {"LicenseShortName": {"value": "CC BY-NC 2.0"}},
    },
    "File:Carol.svg": {"mime": "image/svg+xml"},
    "File:Gone.jpg": None,
}


def _sparql_rows(images_by_mbid: dict[str, list[str]]) -> list[dict[str, Any]]:
    rows = []
    for n, (mbid, titles) in enumerate(sorted(images_by_mbid.items())):
        base = {
            "musicbrainz": {"type": "literal", "value": mbid},
            "item": {"type": "uri", "value": f"{ENTITY}Q{n + 1}"},
        }
        rows += [
            base | {"image": {"type": "uri", "value": f"{FILE_PATH}{t.removeprefix('File:')}"}}
            for t in titles
        ] or [base]
    return rows


class FakeWikimedia:
    """Answers SPARQL and Commons requests from in-memory tables, recording each request."""

    def __init__(self, images_by_mbid: dict[str, list[str]]) -> None:
        self.images_by_mbid = images_by_mbid
        self.requests: list[httpx.Request] = []

    def sparql(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        query = parse_qs(request.content.decode())["query"][0]
        wanted = {mbid: t for mbid, t in self.images_by_mbid.items() if f'"{mbid}"' in query}
        return httpx.Response(200, json={"results": {"bindings": _sparql_rows(wanted)}})

    def commons(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        params = request.url.params
        width = int(params["iiurlwidth"])
        pages = []
        for title in params["titles"].split("|"):
            overrides = COMMONS_FILES.get(title)
            if overrides is None:
                pages.append({"title": title, "missing": True})
                continue
            info = _info(title, width, **overrides)
            if params["iiprop"] == "url":
                info = {k: info[k] for k in ("url", "thumburl", "descriptionurl")}
            pages.append({"title": title, "imageinfo": [info]})
        return httpx.Response(200, json={"batchcomplete": True, "query": {"pages": pages}})

    def clients(self, cache: Path) -> tuple[WikidataClient, images.CommonsClient]:
        def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
            return httpx.Client(
                transport=httpx.MockTransport(handler),
                headers={"User-Agent": images.USER_AGENT},
            )

        wikidata = WikidataClient(
            sparql_url="https://query.example/sparql",
            cache_dir=cache / "wikidata",
            min_interval_s=0,
            http=client(self.sparql),
        )
        commons = images.CommonsClient(
            cache_dir=cache / "commons",
            base_url="https://commons.example/w/api.php",
            min_interval_s=0,
            http=client(self.commons),
        )
        return wikidata, commons


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    snapshot = tmp_path / "snapshot.jsonl.gz"
    write_snapshot(fx.small_catalog(), snapshot)
    engine = make_engine(f"sqlite:///{tmp_path / 'catalog.db'}")
    migrate.upgrade(engine)
    ingest_snapshot(engine, snapshot)
    yield engine
    engine.dispose()


def _rows(engine: Engine) -> dict[str, m.ArtistImage]:
    with session_scope(engine) as session:
        return {r.artist_id: r for r in session.scalars(select(m.ArtistImage))}


IMAGES = {
    "mb-alice": ["File:Alice.jpg"],
    "mb-bob": ["File:Bob.jpg"],
    "mb-carol": ["File:Carol.svg", "File:Gone.jpg"],
}


def test_fetch_keeps_free_raster_images_with_attribution(engine: Engine, tmp_path: Path) -> None:
    fake = FakeWikimedia(IMAGES)
    result = images.run_fetch_images(engine, *fake.clients(tmp_path), now=NOW)

    assert result["artistsWithWikidataItem"] == 3
    assert result["artistsWithWikidataImage"] == 3
    assert result["artistsWithAcceptedImage"] == 1
    # Carol's first file (in title order) is the SVG, so that is the reason counted.
    assert result["artistsSkipped"] == {"nonFreeLicense": 1, "unsupportedFormat": 1}
    assert result["filesRejectedByLicense"] == {"CC BY-NC 2.0": 1}
    assert result["written"] == {"inserted": 1, "updated": 0, "unchanged": 0, "deleted": 0}

    (row,) = _rows(engine).values()
    assert row.artist_id == ids.artist_id("mb-alice")
    assert row.wikidata_id == "Q1"
    assert row.commons_file == "File:Alice.jpg"
    assert row.thumbnail_url.endswith("/330px-Alice.jpg")
    assert row.large_url.endswith("/960px-Alice.jpg")
    assert (row.width, row.height) == (2000, 3000)
    assert row.page_url == "https://commons.wikimedia.org/wiki/Alice.jpg"
    assert row.author == "Jane Photographer"
    assert row.license == "CC BY-SA 4.0"
    assert row.license_url == "https://creativecommons.org/licenses/by-sa/4.0"
    assert row.attribution_required is True


def test_requests_carry_only_the_generic_user_agent(engine: Engine, tmp_path: Path) -> None:
    fake = FakeWikimedia(IMAGES)
    images.run_fetch_images(engine, *fake.clients(tmp_path), now=NOW)
    assert fake.requests
    for request in fake.requests:
        assert request.headers["User-Agent"] == "SongNexus/0.2 (student capstone project)"
        assert "@" not in str(request.url)
        assert "from" not in {k.lower() for k in request.headers}
    # The default clients are built the same way.
    assert images.http_client("application/json").headers["User-Agent"] == images.USER_AGENT


def test_reruns_are_idempotent_and_follow_upstream_changes(engine: Engine, tmp_path: Path) -> None:
    images.run_fetch_images(engine, *FakeWikimedia(IMAGES).clients(tmp_path / "a"), now=NOW)
    again = images.run_fetch_images(
        engine, *FakeWikimedia(IMAGES).clients(tmp_path / "a"), now=LATER
    )
    assert again["written"] == {"inserted": 0, "updated": 0, "unchanged": 1, "deleted": 0}
    assert again["networkRequests"] == 0  # all from the on-disk cache
    (row,) = _rows(engine).values()
    assert row.fetched_at.replace(tzinfo=UTC) == NOW  # unchanged rows keep their time

    # Upstream, Alice's item lost its image: her row goes (fresh cache, new answers).
    removed = images.run_fetch_images(
        engine, *FakeWikimedia({"mb-alice": []}).clients(tmp_path / "b"), now=LATER
    )
    assert removed["written"]["deleted"] == 1
    assert _rows(engine) == {}


def test_dry_run_and_limit_write_nothing_beyond_their_scope(engine: Engine, tmp_path: Path) -> None:
    dry = images.run_fetch_images(
        engine, *FakeWikimedia(IMAGES).clients(tmp_path), now=NOW, dry_run=True
    )
    assert dry["artistsWithAcceptedImage"] == 1
    assert "written" not in dry
    assert _rows(engine) == {}

    limited = images.run_fetch_images(
        engine, *FakeWikimedia(IMAGES).clients(tmp_path / "limit"), now=NOW, limit=1
    )
    assert limited["artistsConsidered"] == 1


def test_an_mbid_on_two_items_gets_no_photo() -> None:
    report = images.ImageReport()
    matches = {"x": images.WikidataMatch(frozenset({"Q1", "Q2"}), ("File:Alice.jpg",))}
    chosen = images.choose_images({"artist": ["x"]}, matches, {}, report)
    assert chosen == {"artist": None}
    assert report.skipped == {"ambiguousItem": 1}


def test_urls_off_wikimedia_media_hosts_are_refused() -> None:
    info = _info("File:A.jpg", 330, thumburl="http://evil.example/a.jpg")
    page: dict[str, Any] = {"title": "File:A.jpg", "imageinfo": [info]}
    assert images.parse_file(page, None, images.ImageReport()) is images.Skip.BAD_URL
