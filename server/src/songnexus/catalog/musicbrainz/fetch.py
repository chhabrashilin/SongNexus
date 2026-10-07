"""Stage 0: fetch raw MusicBrainz data for a seed list and write a snapshot.

This is the only pipeline stage that touches the network. Selection rules are
deterministic given the same upstream data:

* Seed names are resolved with the entity-resolution matcher. Ambiguous names
  fail loudly and must be pinned to an MBID, with a ``pin_reason``, in the seed
  file.
* Per seed artist, the N studio albums with the most MusicBrainz rating votes are
  selected (a transparent, source-provided popularity proxy).
* Per album, one representative release is chosen (official, earliest,
  non-"clean").
* Every non-seed artist credited as primary or featured on a fetched recording
  gets a profile lookup (aliases and genres), so search and filters work for
  them too. The number of profile lookups is capped.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from songnexus.catalog.musicbrainz.client import MusicBrainzClient
from songnexus.catalog.musicbrainz.parsers import Release, split_artist_credit
from songnexus.catalog.musicbrainz.snapshot import write_snapshot
from songnexus.core.resolution import Candidate, Decision, resolve

log = logging.getLogger(__name__)

ARTIST_INC = "aliases+genres+artist-rels+url-rels"
ARTIST_PROFILE_INC = "aliases+genres"
RELEASE_INC = "recordings+artist-credits+labels+artist-rels+recording-level-rels+release-groups"
MAX_RELEASE_GROUP_PAGES = 3
PAGE_SIZE = 100
DEFAULT_MAX_PROFILES = 1500
_COUNTRY_PREFERENCE = {"XW": 0, "US": 1, "GB": 2}


@dataclass(frozen=True)
class Seed:
    """One seed artist: a name, optionally pinned to an MBID by a person."""

    name: str
    mbid: str | None = None
    pin_reason: str | None = None


@dataclass(frozen=True)
class SeedFile:
    """The parsed seed file."""

    seeds: tuple[Seed, ...]
    albums_per_artist: int


@dataclass(frozen=True)
class SeedResolution:
    """How a seed name became an MBID (recorded in the lock file)."""

    name: str
    mbid: str
    method: str
    confidence: float


class SeedResolutionError(RuntimeError):
    """A seed name did not resolve to exactly one artist."""


def load_seeds(path: Path) -> SeedFile:
    """Reads and validates a seed file.

    Raises:
        ValueError: A pinned seed has no ``pin_reason``, or a name repeats.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    seeds = tuple(
        Seed(name=a["name"], mbid=a.get("mbid"), pin_reason=a.get("pin_reason"))
        for a in data["artists"]
    )
    unexplained = [s.name for s in seeds if s.mbid and not s.pin_reason]
    if unexplained:
        raise ValueError(
            f"Pinned seeds need a pin_reason (a recorded human decision): {unexplained}"
        )
    names = [s.name.casefold() for s in seeds]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"Duplicate seed names: {duplicates}")
    return SeedFile(seeds, int(data.get("albums_per_artist", 4)))


def resolve_seed(client: MusicBrainzClient, seed: Seed) -> SeedResolution:
    """Resolves a seed to an MBID, or raises with the candidates a person should review.

    Raises:
        SeedResolutionError: The name is ambiguous or matches nothing.
    """
    if seed.mbid:
        return SeedResolution(seed.name, seed.mbid, "pinned_mbid", 1.0)
    escaped = seed.name.replace('"', '\\"')
    record = client.get(
        "artist_search",
        "artist",
        # Searching aliases too matters for renamed artists ("Kanye West" -> "Ye").
        {"query": f'artist:"{escaped}" OR alias:"{escaped}"', "limit": 10},
    )
    candidates = [
        Candidate(
            entity_id=a["id"],
            name=a["name"],
            aliases=tuple(al["name"] for al in a.get("aliases", [])),
            prior=float(a.get("score", 0)) / 100.0,
            description=a.get("disambiguation", ""),
        )
        for a in record.body.get("artists", [])
    ]
    resolution = resolve(seed.name, candidates)
    if resolution.entity_id is None:
        options = [
            f"{s.candidate.name} [{s.candidate.entity_id}] {s.candidate.description!r} "
            f"score={s.score:.3f}"
            for s in resolution.ranked[:5]
        ]
        raise SeedResolutionError(
            f"Seed {seed.name!r} is {resolution.decision.value}; pin an mbid with a "
            f"pin_reason in the seed file. Candidates: {options}"
        )
    assert resolution.decision is Decision.MATCHED
    return SeedResolution(seed.name, resolution.entity_id, resolution.method, resolution.confidence)


def select_albums(release_groups: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Returns studio albums ranked by rating votes, then release date, then ID."""
    studio = [
        rg
        for rg in release_groups
        if rg.get("primary-type") == "Album"
        and not rg.get("secondary-types")
        and rg.get("first-release-date")
    ]
    studio.sort(
        key=lambda rg: (
            -int((rg.get("rating") or {}).get("votes-count") or 0),
            rg["first-release-date"],
            rg["id"],
        )
    )
    return studio[:limit]


def choose_release(releases: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Picks one representative official release of an album.

    Clean or edited versions are avoided because they often use different
    recordings with sparser credits. Among the rest: earliest date, preferred
    country, fewest tracks (standard rather than deluxe edition), then ID.
    """
    official = [r for r in releases if r.get("status") == "Official"] or releases
    if not official:
        return None

    def key(r: dict[str, Any]) -> tuple[int, str, int, int, str]:
        disambiguation = (r.get("disambiguation") or "").lower()
        track_count = sum(int(m.get("track-count") or 0) for m in r.get("media", []))
        return (
            1 if "clean" in disambiguation or "edited" in disambiguation else 0,
            r.get("date") or "9999",
            _COUNTRY_PREFERENCE.get(r.get("country") or "", 9),
            track_count,
            r["id"],
        )

    return min(official, key=key)


def credited_performers(release_body: dict[str, Any]) -> set[str]:
    """Returns MBIDs of artists credited as primary or featured anywhere on a release."""
    try:
        release = Release.model_validate(release_body)
    except ValidationError:
        return set()
    credits = [release.artist_credit] + [
        track.recording.artist_credit for medium in release.media for track in medium.tracks
    ]
    return {entry.artist.id for credit in credits for entry, _ in split_artist_credit(credit)}


def fetch_artist_bundle(
    client: MusicBrainzClient, mbid: str, albums_per_artist: int
) -> tuple[int, set[str]]:
    """Fetches an artist lookup and its selected albums.

    Returns:
        The number of albums fetched, and the MBIDs of every performer credited
        on them.
    """
    client.get("artist", f"artist/{mbid}", {"inc": ARTIST_INC})

    release_groups: list[dict[str, Any]] = []
    for page in range(MAX_RELEASE_GROUP_PAGES):
        record = client.get(
            "release_groups",
            "release-group",
            {
                "artist": mbid,
                "type": "album",
                "inc": "ratings",
                "limit": PAGE_SIZE,
                "offset": page * PAGE_SIZE,
            },
        )
        batch = record.body.get("release-groups", [])
        release_groups.extend(batch)
        if len(release_groups) >= int(record.body.get("release-group-count", 0)) or not batch:
            break

    fetched = 0
    performers: set[str] = set()
    for rg in select_albums(release_groups, albums_per_artist):
        releases = client.get(
            "releases",
            "release",
            {"release-group": rg["id"], "status": "official", "inc": "media", "limit": PAGE_SIZE},
        ).body.get("releases", [])
        chosen = choose_release(releases)
        if chosen is None:
            log.warning("no release for release group", extra={"release_group": rg["id"]})
            continue
        release = client.get("release", f"release/{chosen['id']}", {"inc": RELEASE_INC})
        performers |= credited_performers(release.body)
        fetched += 1
    return fetched, performers


def run_fetch(
    client: MusicBrainzClient,
    *,
    seeds_path: Path,
    snapshot_path: Path,
    lock_path: Path,
    max_profiles: int = DEFAULT_MAX_PROFILES,
) -> dict[str, Any]:
    """Fetches everything for a seed file and writes the snapshot and lock file.

    Returns:
        Run statistics, including every unresolved seed with its candidates.
    """
    seed_file = load_seeds(seeds_path)
    resolutions: list[SeedResolution] = []
    errors: list[str] = []
    performers: set[str] = set()
    for seed in seed_file.seeds:
        try:
            resolution = resolve_seed(client, seed)
        except SeedResolutionError as exc:
            errors.append(str(exc))
            continue
        resolutions.append(resolution)
        albums, credited = fetch_artist_bundle(client, resolution.mbid, seed_file.albums_per_artist)
        performers |= credited
        log.info(
            "fetched artist", extra={"seed": seed.name, "mbid": resolution.mbid, "albums": albums}
        )

    seed_mbids = {r.mbid for r in resolutions}
    profiles = sorted(performers - seed_mbids)
    skipped_profiles = max(0, len(profiles) - max_profiles)
    for mbid in profiles[:max_profiles]:
        client.get("artist_profile", f"artist/{mbid}", {"inc": ARTIST_PROFILE_INC})

    lock_path.write_text(
        json.dumps(
            {"artists": [asdict(r) for r in resolutions], "unresolved": errors},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    # Only records requested for the current seed list go into the snapshot.
    written = write_snapshot(client.session_records.values(), snapshot_path)
    return {
        "seeds": len(seed_file.seeds),
        "resolved": len(resolutions),
        "unresolved": errors,
        "profiles": min(len(profiles), max_profiles),
        "skippedProfiles": skipped_profiles,
        "records": written,
        "networkRequests": client.network_requests,
        "cacheHits": client.cache_hits,
    }
