"""Stage 0: fetch raw MusicBrainz data for a seed list and write a snapshot.

This is the only pipeline stage that touches the network. Selection rules are
deterministic (given the same upstream data) and documented in
docs/data-pipeline.md:

* seed names are resolved with the entity-resolution matcher; ambiguous names
  fail loudly and must be pinned to an MBID in the seed file;
* per artist, the N studio albums with the most MusicBrainz rating votes are
  selected (a transparent, source-provided popularity proxy);
* per album, one representative release is chosen (earliest, non-"clean").
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from songnexus.integrations.musicbrainz.client import MusicBrainzClient
from songnexus.integrations.musicbrainz.snapshot import RawRecord, write_snapshot
from songnexus.resolution.matcher import Candidate, Decision, resolve

log = logging.getLogger(__name__)

ARTIST_INC = "aliases+genres+artist-rels+url-rels"
RELEASE_INC = "recordings+artist-credits+artist-rels+recording-level-rels+release-groups"
MAX_RELEASE_GROUP_PAGES = 3
PAGE_SIZE = 100
COUNTRY_PREFERENCE = {"XW": 0, "US": 1, "GB": 2}


@dataclass(frozen=True)
class Seed:
    name: str
    mbid: str | None = None


@dataclass(frozen=True)
class SeedResolution:
    name: str
    mbid: str
    method: str
    confidence: float


class SeedResolutionError(RuntimeError):
    pass


def load_seeds(path: Path) -> tuple[list[Seed], int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    seeds = [Seed(name=a["name"], mbid=a.get("mbid")) for a in data["artists"]]
    unexplained = [a["name"] for a in data["artists"] if a.get("mbid") and not a.get("pin_reason")]
    if unexplained:
        raise ValueError(f"Pinned seeds need a pin_reason (a recorded human decision): {unexplained}")
    return seeds, int(data.get("albums_per_artist", 4))


def resolve_seed(client: MusicBrainzClient, seed: Seed) -> SeedResolution:
    if seed.mbid:
        return SeedResolution(seed.name, seed.mbid, "pinned_mbid", 1.0)
    record = client.get(
        # Searching aliases too matters for renamed artists (e.g. "Kanye West" -> "Ye").
        "artist_search",
        "artist",
        {"query": f'artist:"{seed.name}" OR alias:"{seed.name}"', "limit": 10},
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
    if resolution.decision is not Decision.MATCHED or resolution.entity_id is None:
        options = [
            f"{s.candidate.name} [{s.candidate.entity_id}] {s.candidate.description!r} score={s.score:.3f}"
            for s in resolution.ranked[:5]
        ]
        raise SeedResolutionError(
            f"Seed {seed.name!r} is {resolution.decision.value}; pin an mbid in the seed file. Candidates: {options}"
        )
    return SeedResolution(seed.name, resolution.entity_id, resolution.method, resolution.confidence)


def select_albums(release_groups: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Studio albums only, ranked by rating votes (then release date, then id)."""
    studio = [
        rg
        for rg in release_groups
        if rg.get("primary-type") == "Album" and not rg.get("secondary-types") and rg.get("first-release-date")
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
    """Pick one representative official release of an album.

    Clean/edited versions are avoided because they often use different
    recordings with sparser credits. Among the rest: earliest date, preferred
    country, fewest tracks (standard rather than deluxe edition), then id.
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
            COUNTRY_PREFERENCE.get(r.get("country") or "", 9),
            track_count,
            r["id"],
        )

    return min(official, key=key)


def fetch_artist_bundle(client: MusicBrainzClient, mbid: str, albums_per_artist: int) -> int:
    """Fetch artist lookup + selected albums. Returns number of albums fetched."""
    client.get("artist", f"artist/{mbid}", {"inc": ARTIST_INC})

    release_groups: list[dict[str, Any]] = []
    for page in range(MAX_RELEASE_GROUP_PAGES):
        record = client.get(
            "release_groups",
            "release-group",
            {"artist": mbid, "type": "album", "inc": "ratings", "limit": PAGE_SIZE, "offset": page * PAGE_SIZE},
        )
        batch = record.body.get("release-groups", [])
        release_groups.extend(batch)
        if len(release_groups) >= int(record.body.get("release-group-count", 0)) or not batch:
            break

    fetched = 0
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
        client.get("release", f"release/{chosen['id']}", {"inc": RELEASE_INC})
        fetched += 1
    return fetched


def run_fetch(
    client: MusicBrainzClient,
    seeds_path: Path,
    snapshot_path: Path,
    lock_path: Path,
) -> dict[str, Any]:
    seeds, albums_per_artist = load_seeds(seeds_path)
    resolutions: list[SeedResolution] = []
    errors: list[str] = []
    for seed in seeds:
        try:
            resolution = resolve_seed(client, seed)
        except SeedResolutionError as exc:
            errors.append(str(exc))
            continue
        resolutions.append(resolution)
        albums = fetch_artist_bundle(client, resolution.mbid, albums_per_artist)
        log.info("fetched artist", extra={"seed": seed.name, "mbid": resolution.mbid, "albums": albums})

    lock_path.write_text(
        json.dumps({"artists": [r.__dict__ for r in resolutions], "unresolved": errors}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    # Only records requested for the current seed list go into the snapshot.
    records: list[RawRecord] = list(client.session_records.values())
    written = write_snapshot(records, snapshot_path)
    return {
        "seeds": len(seeds),
        "resolved": len(resolutions),
        "unresolved": errors,
        "records": written,
        "network_requests": client.network_requests,
        "cache_hits": client.cache_hits,
    }
