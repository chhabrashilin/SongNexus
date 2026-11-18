"""The data-source registry: every source SongNexus uses or evaluates, with its license (ADR 0005).

This module is the single source of truth. The ingest pipeline registers sources
from it and refuses facts from anything else; ``ListDataSources`` and the About
screen's Resources section serve it; ``docs/resources.md`` is generated from it
(``songnexus resources``, checked in CI).

A source is added here *before* any code reads from it, with the license as the
provider states it and the date that was checked. Sources whose license is
unstated are not used.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Tier(enum.StrEnum):
    """What a source's license allows us to do with it."""

    # CC0 or equivalent: usable in a commercial YouTube Music feature.
    PRODUCTION = "PRODUCTION"
    # Non-commercial terms: the capstone may serve it; a commercial launch drops it by source ID.
    NON_COMMERCIAL = "NON_COMMERCIAL"
    # Offline evaluation only: never stored in the catalog, never served.
    EVALUATION = "EVALUATION"


class Status(enum.StrEnum):
    """Whether the source is wired in yet."""

    IN_USE = "IN_USE"
    PLANNED = "PLANNED"


class Kind(enum.StrEnum):
    """How we obtain the data."""

    API = "API"
    DATA_DUMP = "DATA_DUMP"
    DATASET = "DATASET"  # a published research or Kaggle dataset
    USER_ACCOUNT = "USER_ACCOUNT"  # a listener's own data, through a linked account or export


@dataclass(frozen=True)
class DataSource:
    """One provider of data.

    Attributes:
        id: Stable ID; facts carry it as ``source_id``.
        name: Display name.
        homepage: Where the provider describes the data (an app path for our own pages).
        license: SPDX identifier, or the provider's own terms name when there is none.
        license_url: Where the license or terms are stated.
        tier: What the license allows.
        status: Whether code reads from it yet.
        kind: How we obtain it.
        feeds: The SongNexus features that use it, in plain words.
        attribution: Text shown wherever its data appears ("" when not required).
        checked_on: ISO date the license was last checked against ``license_url``.
        notes: Caveats a reviewer must know (coverage, freshness, conditions).
    """

    id: str
    name: str
    homepage: str
    license: str
    license_url: str
    tier: Tier
    status: Status
    kind: Kind
    feeds: tuple[str, ...]
    attribution: str
    checked_on: str
    notes: str = ""


SOURCES: tuple[DataSource, ...] = (
    # --- Catalog: facts about artists, recordings and their credits -------------------------
    DataSource(
        id="musicbrainz",
        name="MusicBrainz",
        homepage="https://musicbrainz.org",
        license="CC0-1.0",
        license_url="https://musicbrainz.org/doc/About/Data_License",
        tier=Tier.PRODUCTION,
        status=Status.IN_USE,
        kind=Kind.API,
        feeds=(
            "artists, recordings, releases and labels",
            "credits and artist relationships (every connection)",
            "collaborations, six degrees, compare, the daily puzzle",
        ),
        attribution="Data from MusicBrainz",
        checked_on="2026-10-07",
        notes="Core data only. Fetched at no more than one request per 1.1 s with an identifying "
        "User-Agent, as MusicBrainz asks.",
    ),
    DataSource(
        id="musicbrainz-supplementary",
        name="MusicBrainz genres",
        homepage="https://musicbrainz.org/doc/Genre",
        license="CC-BY-NC-SA-3.0",
        license_url="https://musicbrainz.org/doc/About/Data_License",
        tier=Tier.NON_COMMERCIAL,
        status=Status.IN_USE,
        kind=Kind.API,
        feeds=("artist genres", "genre filters and shared genres in compare"),
        attribution="Genre data from MusicBrainz (CC BY-NC-SA 3.0)",
        checked_on="2026-10-07",
        notes="Tag-derived genre associations. Kept apart from core data (ADR 0003); replaced by "
        "Discogs and Wikidata genres for commercial use.",
    ),
    DataSource(
        id="discogs",
        name="Discogs data dumps",
        homepage="https://data.discogs.com",
        license="CC0-1.0",
        license_url="https://support.discogs.com/hc/en-us/articles/360009334593",
        tier=Tier.PRODUCTION,
        status=Status.IN_USE,
        kind=Kind.DATA_DUMP,
        feeds=("artist genres (commercial-safe)", "genre filters and shared genres in compare"),
        attribution="Data from Discogs",
        checked_on="2026-11-01",
        notes="Monthly XML dumps of artists, labels, masters and releases are CC0; we read the "
        "masters dump (main artists, genres, styles). API-only 'Restricted Data' (images, "
        "marketplace) is not used. Artists are joined through MusicBrainz and Wikidata links, "
        "never by name; styles map onto the MusicBrainz genre list by name or a reviewed table.",
    ),
    DataSource(
        id="wikidata",
        name="Wikidata",
        homepage="https://www.wikidata.org",
        license="CC0-1.0",
        license_url="https://www.wikidata.org/wiki/Wikidata:Licensing",
        tier=Tier.PRODUCTION,
        status=Status.IN_USE,
        kind=Kind.API,
        feeds=(
            "genre hierarchy (subgenres)",
            "links from MusicBrainz artists to Discogs",
            "Around you: the campuses and cities listeners can join",
            "artist photos: which Commons file shows an artist",
        ),
        attribution="Data from Wikidata",
        checked_on="2026-11-16",
        notes="Structured data is CC0. Used for 'subclass of' (P279) links between items carrying "
        "MusicBrainz genre IDs (P8052), and for items carrying both a MusicBrainz artist ID "
        "(P434) and a Discogs artist ID (P1953). The Around you list is the largest US "
        "universities by student count (P2196) plus a few abroad, their cities, US cities over "
        "100,000 people and national capitals, rebuilt with `songnexus fetch-communities`.",
    ),
    DataSource(
        id="wikimedia-commons",
        name="Wikimedia Commons",
        homepage="https://commons.wikimedia.org",
        license="Per file: public domain, CC0, CC BY or CC BY-SA",
        license_url="https://commons.wikimedia.org/wiki/Commons:Licensing",
        tier=Tier.PRODUCTION,
        status=Status.IN_USE,
        kind=Kind.API,
        feeds=("artist photos",),
        attribution="Each photo is credited with its author, license and Commons file page",
        checked_on="2026-11-16",
        notes="Found through the image (P18) on the artist's Wikidata item, matched by MusicBrainz "
        "ID (P434); fetched with `songnexus fetch-images` (ADR 0009). Each file carries its own "
        "license: only public domain, CC0, CC BY and CC BY-SA raster images are kept; non-free, "
        "unlicensed and non-commercial files are skipped. Images are hot-linked from Wikimedia's "
        "media hosts (upload.wikimedia.org, thumb.wikimedia.org), never copied, and the API "
        "returns the author, license and file page with every photo.",
    ),
    # --- Audio descriptors and listening -------------------------------------------------
    DataSource(
        id="acousticbrainz",
        name="AcousticBrainz",
        homepage="https://acousticbrainz.org",
        license="CC0-1.0",
        license_url="https://acousticbrainz.org/download",
        tier=Tier.PRODUCTION,
        status=Status.IN_USE,
        kind=Kind.API,
        feeds=("song comparison: tempo, key, loudness, mood and other audio descriptors",),
        attribution="Audio data from AcousticBrainz",
        checked_on="2026-11-01",
        notes="Data collection stopped in 2022; the API still serves the final dataset. Coverage "
        "is partial and keyed by MusicBrainz recording ID; songs without data say so. The "
        "voice-gender and genre classifiers are not used.",
    ),
    DataSource(
        id="listenbrainz",
        name="ListenBrainz",
        homepage="https://listenbrainz.org",
        license="CC0-1.0",
        license_url="https://listenbrainz.org/terms-of-service/",
        tier=Tier.PRODUCTION,
        status=Status.IN_USE,
        kind=Kind.API,
        feeds=(
            "listener overlap in artist comparison",
            "'often played with' on artist pages",
        ),
        attribution="Listening data from ListenBrainz",
        checked_on="2026-11-01",
        notes="Public listens are CC0. Only aggregates are fetched: listener and listen counts per "
        "artist, and the session-based similar-artists ranking. Overlap is shown only when both "
        "artists have at least 50 listeners, always with the counts.",
    ),
    # --- Offline evaluation only ---------------------------------------------------------
    DataSource(
        id="kaggle-spotify-tracks",
        name="Spotify Tracks Dataset (Kaggle, maharshipandya)",
        homepage="https://www.kaggle.com/datasets/maharshipandya/-spotify-tracks-dataset",
        license="CC0-1.0 (as stated by the uploader)",
        license_url="https://www.kaggle.com/datasets/maharshipandya/-spotify-tracks-dataset",
        tier=Tier.EVALUATION,
        status=Status.PLANNED,
        kind=Kind.DATASET,
        feeds=("evaluating song similarity against genre labels",),
        attribution="",
        checked_on="2026-11-01",
        notes="About 114,000 tracks across 125 genres with audio features. The uploader states "
        "CC0, but the values come from the Spotify Web API, whose terms the uploader cannot waive. "
        "Treated as evaluation-only. Not used yet: downloading needs a Kaggle account, so song "
        "similarity is evaluated against genre agreement instead (eval-songs).",
    ),
    DataSource(
        id="lastfm-360k",
        name="Last.fm 360K and 1K users (Celma, 2010)",
        homepage="https://zenodo.org/records/6090214",
        license="Non-commercial research use, with permission of Last.fm",
        license_url="https://zenodo.org/records/6090214",
        tier=Tier.EVALUATION,
        status=Status.IN_USE,
        kind=Kind.DATASET,
        feeds=("evaluating listener overlap against an independent population",),
        attribution="Last.fm dataset, Ò. Celma (2010)",
        checked_on="2026-11-01",
        notes="Per-user artist play counts with MusicBrainz artist IDs; collected 2008-2009, so it "
        "measures agreement, not current overlap. Also mirrored on Kaggle.",
    ),
    # --- A listener's own data -----------------------------------------------------------
    DataSource(
        id="user-listening",
        name="Your listening history",
        homepage="/privacy",
        license="The listener's own data",
        license_url="/privacy",
        tier=Tier.PRODUCTION,
        status=Status.IN_USE,
        kind=Kind.USER_ACCOUNT,
        feeds=(
            "Library: your artists and playlist analysis",
            "Around you: campus and city charts, from listeners who opt in",
        ),
        attribution="",
        checked_on="2026-10-07",
        notes="Imported files are parsed on the device; only artist names reach the server. Linked "
        "accounts (R2-6) add each provider under its own API terms. Around you charts use only "
        "members who opted in, and only once 10 have listening data; an artist needs 3 listeners "
        "and counts are shown as ranges.",
    ),
)

BY_ID: dict[str, DataSource] = {s.id: s for s in SOURCES}

# Sources that may assert artist-genre associations (ADR 0003, ADR 0005).
GENRE_SOURCE_IDS = ("musicbrainz-supplementary", "discogs")


def catalog_sources() -> tuple[DataSource, ...]:
    """Returns the sources whose facts may be stored in the catalog.

    That excludes evaluation-only datasets and listeners' own data.
    """
    return tuple(
        s for s in SOURCES if s.tier is not Tier.EVALUATION and s.kind is not Kind.USER_ACCOUNT
    )


_TIER_HEADINGS = {
    Tier.PRODUCTION: (
        "Production-safe",
        "CC0 or equivalent. Usable in a commercial YouTube Music feature.",
    ),
    Tier.NON_COMMERCIAL: (
        "Non-commercial",
        "Served in the capstone build only. A commercial launch removes these facts by source ID.",
    ),
    Tier.EVALUATION: (
        "Evaluation only",
        "Used offline to check our results against an independent signal. Never stored in the "
        "catalog, never shown to listeners.",
    ),
}


_KIND_LABELS = {
    Kind.API: "its API",
    Kind.DATA_DUMP: "published data dumps",
    Kind.DATASET: "a published dataset",
    Kind.USER_ACCOUNT: "the listener's own files or linked accounts",
}


def _link(text: str, url: str) -> str:
    return f"[{text}]({url})" if url.startswith("http") else text


def render_markdown() -> str:
    """Returns ``docs/resources.md``, generated from the registry."""
    lines = [
        "# Resources: data sources and licenses",
        "",
        "<!-- Generated from server/src/songnexus/catalog/sources.py by `songnexus resources`."
        " Do not edit by hand; CI fails when this file is out of date. -->",
        "",
        "Every fact SongNexus shows carries the ID of the source that asserted it. This page lists "
        "every source we use or evaluate, what it feeds, its license, and when the license was "
        "checked. The policy behind the tiers is [ADR 0005](adr/0005-data-source-policy.md); the "
        "same list is served by `ListDataSources` (`GET /v1/dataSources`) and shown on the app's "
        "About page.",
        "",
        "Status **Planned** means the source is approved but no code reads from it yet; the plan "
        "milestone that wires it in is in [plans/r2-plan.md](plans/r2-plan.md).",
        "",
        "## Summary",
        "",
        "| Source | License | Tier | Status | Feeds |",
        "|---|---|---|---|---|",
    ]
    for s in SOURCES:
        lines.append(
            f"| {_link(s.name, s.homepage)} | {s.license} | {_TIER_HEADINGS[s.tier][0]} | "
            f"{s.status.value.replace('_', ' ').title()} | {'; '.join(s.feeds)} |"
        )
    for tier, (heading, meaning) in _TIER_HEADINGS.items():
        lines += ["", f"## {heading}", "", meaning]
        for s in (s for s in SOURCES if s.tier is tier):
            lines += [
                "",
                f"### {s.name}",
                "",
                f"- **ID:** `{s.id}`",
                f"- **Obtained via:** {_KIND_LABELS[s.kind]}",
                f"- **License:** {_link(s.license, s.license_url)} (checked {s.checked_on})",
                f"- **Feeds:** {'; '.join(s.feeds)}",
            ]
            if s.attribution:
                lines.append(f"- **Attribution:** “{s.attribution}”")
            if s.notes:
                lines.append(f"- **Notes:** {s.notes}")
    lines += [
        "",
        "## Adding a source",
        "",
        "1. Read the provider's license or terms; record the SPDX ID (or the terms' name), the URL "
        "and today's date.",
        "2. Add a `DataSource` to `sources.py` with status `PLANNED` and the right tier. "
        "Unclear or unstated license: do not add it.",
        "3. Run `uv run songnexus resources` and commit the regenerated page with the code that "
        "first reads the source, switching its status to `IN_USE`.",
        "",
    ]
    return "\n".join(lines)
