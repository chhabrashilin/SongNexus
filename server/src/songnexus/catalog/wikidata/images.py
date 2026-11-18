"""Find freely licensed artist photos on Wikimedia Commons through Wikidata (ADR 0009).

Two steps, both through the shared polite, cached HTTP client:

1. Wikidata SPARQL, in batches: MusicBrainz artist ID (P434) -> item -> image (P18).
2. Commons ``imageinfo``, at most 50 files a request: a ~330 px and a ~960 px
   thumbnail URL, the original size, the file page, and the license metadata.

Only raster images under a free license (public domain, CC0, CC BY, CC BY-SA)
are accepted; everything else is skipped and counted. Requests carry a generic
User-Agent and nothing about the person running the command.
"""

from __future__ import annotations

import enum
import html
import logging
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
from sqlalchemy import Engine

from songnexus.catalog.http import PoliteClient, SourceRequestError
from songnexus.catalog.wikidata.fetch import WikidataClient, bindings
from songnexus.storage.artist_images import (
    ImageRecord,
    artist_ids_by_musicbrainz_id,
    detail_levels,
    write_images,
)
from songnexus.storage.db import session_scope

log = logging.getLogger(__name__)

# Generic on purpose: Wikimedia asks for an identifying User-Agent, and the
# project name is enough. Never a personal name or address (ADR 0009).
USER_AGENT = "SongNexus/0.2 (student capstone project)"
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
SPARQL_BATCH = 400  # MusicBrainz IDs per query, as in the artist-link fetch
COMMONS_BATCH = 50  # the API's limit on titles per request for ordinary clients
# Commons serves thumbnails at standard widths; these two are standard buckets.
THUMBNAIL_WIDTH = 330
LARGE_WIDTH = 960
COMMONS_MIN_INTERVAL_S = 1.0
# Wikimedia's media hosts: scaled thumbnails come from thumb., originals (and
# files narrower than the asked width) from upload. The web CSP allows both.
MEDIA_HOSTS = frozenset({"upload.wikimedia.org", "thumb.wikimedia.org"})
ACCEPTED_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_AUTHOR_CHARS = 512
_TIMEOUT_S = 60.0

_FILE_PATH_MARKER = "/Special:FilePath/"
_CC_FREE = re.compile(r"^cc[ -]by(?:[ -]sa)?(?:[ -]\d(?:\.\d)?)?(?:[ -][a-z]{2,})*$")
_NON_FREE_TOKENS = frozenset({"nc", "nd"})


class Skip(enum.StrEnum):
    """Why an artist with a Wikidata image got no photo."""

    AMBIGUOUS_ITEM = "ambiguousItem"  # the MusicBrainz ID is on more than one item
    MISSING_FILE = "missingFile"  # Commons does not know the file
    UNSUPPORTED_FORMAT = "unsupportedFormat"  # not JPEG, PNG or WebP (SVG, TIFF, GIF...)
    MISSING_LICENSE = "missingLicense"
    NON_FREE_LICENSE = "nonFreeLicense"
    BAD_URL = "badUrl"  # an image URL not on a Wikimedia media host over HTTPS


@dataclass(frozen=True)
class CommonsFile:
    """What Commons says about one file, already filtered and cleaned."""

    title: str  # "File:Name.jpg"
    thumbnail_url: str
    large_url: str
    width: int
    height: int
    page_url: str
    author: str | None
    license: str
    license_url: str | None
    attribution_required: bool


@dataclass
class ImageReport:
    """Coverage and outcome of one run.

    ``skipped`` counts artists (with a Wikidata image but no accepted photo) by
    the reason their first file failed; the ``rejected*`` counters count files.
    """

    artists_with_musicbrainz_id: int = 0
    artists_considered: int = 0
    artists_with_wikidata_item: int = 0
    artists_with_wikidata_image: int = 0
    artists_with_accepted_image: int = 0
    skipped: Counter[str] = field(default_factory=Counter)
    rejected_licenses: Counter[str] = field(default_factory=Counter)
    rejected_mime: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        """Returns the report as JSON-ready camelCase keys."""
        return {
            "artistsWithMusicbrainzId": self.artists_with_musicbrainz_id,
            "artistsConsidered": self.artists_considered,
            "artistsWithWikidataItem": self.artists_with_wikidata_item,
            "artistsWithWikidataImage": self.artists_with_wikidata_image,
            "artistsWithAcceptedImage": self.artists_with_accepted_image,
            "artistsSkipped": dict(sorted(self.skipped.items())),
            "filesRejectedByLicense": dict(self.rejected_licenses.most_common(15)),
            "filesRejectedByMimeType": dict(self.rejected_mime.most_common()),
        }


def http_client(accept: str) -> httpx.Client:
    """Returns an HTTP client with the generic User-Agent and nothing else identifying."""
    return httpx.Client(
        timeout=httpx.Timeout(_TIMEOUT_S, connect=10.0),
        headers={"User-Agent": USER_AGENT, "Accept": accept},
    )


class CommonsClient(PoliteClient):
    """Calls the Wikimedia Commons Action API (JSON, format version 2)."""

    def __init__(
        self,
        *,
        cache_dir: Path,
        base_url: str = COMMONS_API_URL,
        min_interval_s: float = COMMONS_MIN_INTERVAL_S,
        http: httpx.Client | None = None,
    ) -> None:
        """Creates a client; ``http`` defaults to one with the generic User-Agent."""
        super().__init__(
            source="wikimedia-commons",
            base_url=base_url,
            cache_dir=cache_dir,
            min_interval_s=min_interval_s,
            http=http or http_client("application/json"),
        )

    def extra_params(self) -> dict[str, str | int]:
        """Every request asks for JSON in format version 2 (pages as a list)."""
        return {"format": "json", "formatversion": 2}


def images_query(musicbrainz_ids: Iterable[str]) -> str:
    """Returns the SPARQL query for the items and P18 images of MusicBrainz artist IDs."""
    values = " ".join(f'"{mbid}"' for mbid in sorted(musicbrainz_ids))
    return (
        "SELECT ?musicbrainz ?item ?image WHERE {\n"
        f"  VALUES ?musicbrainz {{ {values} }}\n"
        "  ?item wdt:P434 ?musicbrainz .\n"
        "  OPTIONAL { ?item wdt:P18 ?image . }\n"
        "}"
    )


def file_title(image_value: str) -> str | None:
    """Returns ``File:Name.jpg`` for a P18 value (a Special:FilePath URL), or None."""
    path = urlsplit(image_value).path
    if _FILE_PATH_MARKER not in path:
        return None
    name = unquote(path.split(_FILE_PATH_MARKER, 1)[1]).replace("_", " ").strip()
    return f"File:{name}" if name else None


@dataclass(frozen=True)
class WikidataMatch:
    """The Wikidata items and image files found for one MusicBrainz ID."""

    items: frozenset[str]  # QIDs
    files: tuple[str, ...]  # "File:..." titles, sorted


def parse_images(rows: Iterable[Mapping[str, str]]) -> dict[str, WikidataMatch]:
    """Groups SPARQL rows into {MusicBrainz ID: items and image files}."""
    items: dict[str, set[str]] = defaultdict(set)
    files: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        mbid = row.get("musicbrainz")
        item = row.get("item", "").rsplit("/", 1)[-1]
        if not mbid or not item:
            continue
        items[mbid].add(item)
        title = file_title(row.get("image", ""))
        if title:
            files[mbid].add(title)
    return {
        mbid: WikidataMatch(frozenset(qids), tuple(sorted(files.get(mbid, ()))))
        for mbid, qids in items.items()
    }


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(value: str) -> str:
    """Returns the text of an HTML fragment: tags dropped, entities decoded, spaces collapsed."""
    extractor = _TextExtractor()
    extractor.feed(value)
    extractor.close()
    return " ".join(html.unescape("".join(extractor.parts)).split())


def is_free_license(short_name: str) -> bool:
    """True for public domain, CC0, CC BY and CC BY-SA (any version or port).

    Non-commercial and no-derivatives variants, GFDL-only, fair use and anything
    unrecognized are not free enough to show everywhere the API is used.
    """
    name = " ".join(short_name.lower().replace("_", " ").split())
    if not name:
        return False
    if name in {"pd", "cc0", "cc0 1.0", "cc-zero"} or name.startswith(("public domain", "pd-")):
        return True
    if set(re.split(r"[ -]", name)) & _NON_FREE_TOKENS:
        return False
    return _CC_FREE.match(name) is not None


def _meta(extmetadata: Mapping[str, Any], key: str) -> str:
    entry = extmetadata.get(key)
    return str(entry.get("value", "")).strip() if isinstance(entry, Mapping) else ""


def _is_media_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in MEDIA_HOSTS


def parse_file(
    page: Mapping[str, Any], large_url: str | None, report: ImageReport
) -> CommonsFile | Skip:
    """Returns the accepted file for one ``imageinfo`` page, or why it was refused.

    Refused licenses and formats are also counted in ``report``.
    """
    infos = page.get("imageinfo") or []
    if page.get("missing") or not infos:
        return Skip.MISSING_FILE
    info: Mapping[str, Any] = infos[0]
    mime = str(info.get("mime", ""))
    if mime not in ACCEPTED_MIME:
        report.rejected_mime[mime or "unknown"] += 1
        return Skip.UNSUPPORTED_FORMAT
    meta: Mapping[str, Any] = info.get("extmetadata") or {}
    license_name = _meta(meta, "LicenseShortName")
    if not license_name:
        return Skip.MISSING_LICENSE
    if _meta(meta, "NonFree").lower() == "true" or not is_free_license(license_name):
        report.rejected_licenses[license_name] += 1
        return Skip.NON_FREE_LICENSE
    thumbnail = str(info.get("thumburl") or info.get("url") or "")
    large = large_url or thumbnail
    if not (_is_media_url(thumbnail) and _is_media_url(large)):
        return Skip.BAD_URL
    author = plain_text(_meta(meta, "Artist"))[:MAX_AUTHOR_CHARS] or None
    license_url = _meta(meta, "LicenseUrl")
    return CommonsFile(
        title=str(page["title"]),
        thumbnail_url=thumbnail,
        large_url=large,
        width=int(info.get("width") or 0),
        height=int(info.get("height") or 0),
        page_url=str(info.get("descriptionurl") or ""),
        author=author,
        license=plain_text(license_name),
        license_url=license_url if license_url.startswith("http") else None,
        attribution_required=_meta(meta, "AttributionRequired").lower() != "false",
    )


def _query_pages(
    client: CommonsClient, titles: Sequence[str], params: dict[str, str | int]
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    """Returns ({title: page}, {asked title: resolved title}) for one batch, across continues."""
    pages: dict[str, Mapping[str, Any]] = {}
    aliases: dict[str, str] = {}
    base: dict[str, str | int] = {
        "action": "query",
        "titles": "|".join(titles),
        "redirects": 1,
        **params,
    }
    cont: dict[str, str | int] = {}
    while True:
        body = client.get("imageinfo", "", base | cont).body
        if "error" in body:
            raise SourceRequestError(f"Commons API error: {body['error']}")
        query = body.get("query", {})
        for step in ("normalized", "redirects"):
            for entry in query.get(step, []):
                aliases[str(entry["from"])] = str(entry["to"])
        for page in query.get("pages", []):
            title = str(page.get("title", ""))
            # A continued response repeats pages; keep the one that has image info.
            if title not in pages or page.get("imageinfo"):
                pages[title] = page
        next_cont = body.get("continue")
        if not next_cont:
            return pages, aliases
        cont = {k: v for k, v in next_cont.items() if isinstance(v, str | int)}


def _resolve(title: str, aliases: Mapping[str, str]) -> str:
    seen = set()
    while title in aliases and title not in seen:
        seen.add(title)
        title = aliases[title]
    return title


def fetch_files(
    client: CommonsClient, titles: Iterable[str], report: ImageReport
) -> dict[str, CommonsFile | Skip]:
    """Returns {requested title: accepted file, or why it was refused} for every title."""
    ordered = sorted(set(titles))
    result: dict[str, CommonsFile | Skip] = {}
    for start in range(0, len(ordered), COMMONS_BATCH):
        batch = ordered[start : start + COMMONS_BATCH]
        pages, aliases = _query_pages(
            client,
            batch,
            {
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": THUMBNAIL_WIDTH,
                "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|"
                "AttributionRequired|NonFree",
            },
        )
        large_pages, large_aliases = _query_pages(
            client,
            batch,
            {"prop": "imageinfo", "iiprop": "url", "iiurlwidth": LARGE_WIDTH},
        )
        for title in batch:
            page = pages.get(_resolve(title, aliases))
            large_page = large_pages.get(_resolve(title, large_aliases)) or {}
            large_infos = large_page.get("imageinfo") or [{}]
            large_url = large_infos[0].get("thumburl") or large_infos[0].get("url")
            result[title] = parse_file(page or {"missing": True}, large_url, report)
    return result


def choose_images(
    artists: Mapping[str, Sequence[str]],
    matches: Mapping[str, WikidataMatch],
    files: Mapping[str, CommonsFile | Skip],
    report: ImageReport,
) -> dict[str, ImageRecord | None]:
    """Picks one image per artist: the first accepted file, in title order.

    Args:
        artists: {artist ID: its MusicBrainz IDs}.
        matches: Wikidata results by MusicBrainz ID.
        files: Commons results by file title.
        report: Updated with item and image coverage.
    """
    chosen: dict[str, ImageRecord | None] = {}
    for artist_id, mbids in sorted(artists.items()):
        found = [matches[mbid] for mbid in mbids if mbid in matches]
        items = frozenset().union(*(match.items for match in found))
        candidates = sorted({title for match in found for title in match.files})
        chosen[artist_id] = None
        if items:
            report.artists_with_wikidata_item += 1
        if not candidates:
            continue
        report.artists_with_wikidata_image += 1
        if len(items) > 1:
            # One MusicBrainz artist on two items is a data error; a photo of the
            # wrong person is worse than none.
            report.skipped[Skip.AMBIGUOUS_ITEM] += 1
            continue
        outcomes = [files.get(t, Skip.MISSING_FILE) for t in candidates]
        accepted = next((o for o in outcomes if isinstance(o, CommonsFile)), None)
        if accepted is None:
            report.skipped[next(o for o in outcomes if isinstance(o, Skip))] += 1
            continue
        report.artists_with_accepted_image += 1
        chosen[artist_id] = ImageRecord(
            wikidata_id=next(iter(items)),
            commons_file=accepted.title,
            thumbnail_url=accepted.thumbnail_url,
            large_url=accepted.large_url,
            width=accepted.width,
            height=accepted.height,
            page_url=accepted.page_url,
            author=accepted.author,
            license=accepted.license,
            license_url=accepted.license_url,
            attribution_required=accepted.attribution_required,
        )
    return chosen


_DETAIL_ORDER = {"full": 0, "profile": 1, "stub": 2}


def select_artists(
    musicbrainz_ids: Mapping[str, str], detail_levels: Mapping[str, str], limit: int | None
) -> dict[str, list[str]]:
    """Returns {artist ID: MusicBrainz IDs} for the artists to process.

    Best-known artists (seeds, then profiles, then stubs) come first, so a
    ``limit`` covers the artists people see most.
    """
    by_artist: dict[str, list[str]] = defaultdict(list)
    for mbid, artist_id in musicbrainz_ids.items():
        if artist_id in detail_levels:
            by_artist[artist_id].append(mbid)
    ordered = sorted(
        by_artist, key=lambda a: (_DETAIL_ORDER.get(detail_levels[a], len(_DETAIL_ORDER)), a)
    )
    if limit is not None:
        ordered = ordered[:limit]
    return {artist_id: sorted(by_artist[artist_id]) for artist_id in ordered}


def find_images(
    wikidata: WikidataClient,
    commons: CommonsClient,
    artists: Mapping[str, Sequence[str]],
    report: ImageReport,
) -> dict[str, ImageRecord | None]:
    """Looks up every artist's photo; returns {artist ID: image or None}.

    Raises:
        SourceRequestError: A request failed permanently.
    """
    mbids = sorted({mbid for ids in artists.values() for mbid in ids})
    matches: dict[str, WikidataMatch] = {}
    for start in range(0, len(mbids), SPARQL_BATCH):
        record = wikidata.sparql(images_query(mbids[start : start + SPARQL_BATCH]))
        matches.update(parse_images(bindings(record)))
    titles = {title for match in matches.values() for title in match.files}
    files = fetch_files(commons, titles, report)
    return choose_images(artists, matches, files, report)


def run_fetch_images(
    engine: Engine,
    wikidata: WikidataClient,
    commons: CommonsClient,
    *,
    now: datetime,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fetches photos for catalog artists and stores them (unless ``dry_run``).

    Idempotent: unchanged answers write nothing; an artist whose photo is gone
    or no longer acceptable loses its row. Artists outside ``limit`` are untouched.

    Raises:
        SourceRequestError: A request failed permanently; nothing is written.
    """
    with session_scope(engine) as session:
        mapping = artist_ids_by_musicbrainz_id(session)
        levels = detail_levels(session)
    artists = select_artists(mapping, levels, limit)
    report = ImageReport(
        artists_with_musicbrainz_id=len({a for a in mapping.values() if a in levels}),
        artists_considered=len(artists),
    )
    chosen = find_images(wikidata, commons, artists, report)
    result: dict[str, Any] = {"dryRun": dry_run, **report.as_dict()}
    if not dry_run:
        with session_scope(engine) as session:
            stats = write_images(session, chosen, now)
        result["written"] = {
            "inserted": stats.inserted,
            "updated": stats.updated,
            "unchanged": stats.unchanged,
            "deleted": stats.deleted,
        }
    result["networkRequests"] = wikidata.network_requests + commons.network_requests
    result["cacheHits"] = wikidata.cache_hits + commons.cache_hits
    log.info("fetch-images finished", extra={k: v for k, v in result.items() if k != "skipped"})
    return result
