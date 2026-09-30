"""Synthetic MusicBrainz-shaped records for tests.

All entities here are fictional ("Alpha Rapper", "Delta Producer", ...) so a
test fixture can never be mistaken for real music data. Shapes mirror the
MusicBrainz JSON the parsers consume.

Graph encoded by ``synthetic_records()`` (artist-level view):

    Alpha Rapper --performed_with--> Beta Singer        (track "Skyline", Beta featured)
    Delta Producer --produced_for--> Alpha, Beta        (track "Skyline")
    Delta Producer --produced_for--> Gamma Pianist      (track "Nocturne")
    Epsilon Drummer --contributed_to--> Gamma Pianist   (drums on "Nocturne")
    Epsilon Drummer --member_of--> Zeta Quartet         (artist relationship)
    Gamma Pianist --member_of--> Zeta Quartet           (artist relationship)
    Eta Engineer --engineered--> Alpha                  (track "Skyline", mix)
    Theta Loner                                         (isolated, own album)
"""

from __future__ import annotations

import uuid
from typing import Any

from songnexus.integrations.musicbrainz.snapshot import RawRecord

_NS = uuid.UUID("00000000-0000-0000-0000-00000000a11c")


def mbid(label: str) -> str:
    return str(uuid.uuid5(_NS, label))


ARTISTS = {
    "alpha": ("Alpha Rapper", "Person"),
    "beta": ("Beta Singer", "Person"),
    "gamma": ("Gamma Pianist", "Person"),
    "delta": ("Delta Producer", "Person"),
    "epsilon": ("Epsilon Drummer", "Person"),
    "zeta": ("Zeta Quartet", "Group"),
    "eta": ("Eta Engineer", "Person"),
    "theta": ("Theta Loner", "Person"),
}


def ref(key: str) -> dict[str, Any]:
    name, kind = ARTISTS[key]
    return {"id": mbid(key), "name": name, "sort-name": name, "type": kind, "country": "XX", "disambiguation": ""}


def credit(*entries: tuple[str, str, str]) -> list[dict[str, Any]]:
    """entries: (artist key, credited name or '', joinphrase)."""
    return [{"name": name or ARTISTS[key][0], "joinphrase": join, "artist": ref(key)} for key, name, join in entries]


def rel(rel_type: str, target: str, direction: str = "backward", attributes: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": rel_type,
        "direction": direction,
        "target-type": "artist",
        "artist": ref(target),
        "attributes": attributes or [],
        "begin": None,
        "end": None,
    }


def recording(
    key: str,
    title: str,
    artist_credit: list[dict[str, Any]],
    relations: list[dict[str, Any]] | None = None,
    length: int = 200_000,
) -> dict[str, Any]:
    return {
        "id": mbid(f"rec:{key}"),
        "title": title,
        "length": length,
        "first-release-date": "2020-01-01",
        "artist-credit": artist_credit,
        "relations": relations or [],
    }


def release(
    key: str,
    title: str,
    artist_credit: list[dict[str, Any]],
    recordings: list[dict[str, Any]],
    relations: list[dict[str, Any]] | None = None,
) -> RawRecord:
    body = {
        "id": mbid(f"release:{key}"),
        "title": title,
        "date": "2020-01-01",
        "artist-credit": artist_credit,
        "release-group": {
            "id": mbid(f"rg:{key}"),
            "title": title,
            "primary-type": "Album",
            "first-release-date": "2020-01-01",
        },
        "media": [
            {
                "position": 1,
                "tracks": [
                    {"id": mbid(f"trk:{key}:{i}"), "position": i + 1, "title": r["title"], "recording": r}
                    for i, r in enumerate(recordings)
                ],
            }
        ],
        "relations": relations or [],
    }
    return RawRecord(
        "release",
        f"release/{body['id']}?inc=test",
        f"https://example.test/release/{body['id']}",
        "2026-01-01T00:00:00+00:00",
        body,
    )


def artist_lookup(
    key: str,
    aliases: list[str] | None = None,
    genres: list[tuple[str, int]] | None = None,
    relations: list[dict[str, Any]] | None = None,
) -> RawRecord:
    body = {
        **ref(key),
        "life-span": {"begin": "1990", "end": None},
        "aliases": [{"name": a, "type": "Artist name", "locale": None} for a in aliases or []],
        "genres": [{"name": g, "count": c} for g, c in genres or []],
        "relations": relations or [],
    }
    return RawRecord(
        "artist",
        f"artist/{mbid(key)}?inc=test",
        f"https://example.test/artist/{mbid(key)}",
        "2026-01-01T00:00:00+00:00",
        body,
    )


def synthetic_records() -> list[RawRecord]:
    skyline = recording(
        "skyline",
        "Skyline (feat. Beta Singer)",
        credit(("alpha", "", " feat. "), ("beta", "B. Singer", "")),
        [rel("producer", "delta"), rel("mix", "eta")],
    )
    # A second recording of the same song (e.g. a remaster) must merge into one track.
    skyline_remaster = recording(
        "skyline-remaster",
        "Skyline - Remastered 2021",
        credit(("alpha", "", " feat. "), ("beta", "", "")),
        [rel("producer", "delta")],
    )
    nocturne = recording(
        "nocturne",
        "Nocturne",
        credit(("gamma", "", "")),
        [rel("producer", "delta"), rel("instrument", "epsilon", attributes=["drums"])],
    )
    solo = recording("solo", "Alone Again", credit(("theta", "", "")))
    return [
        artist_lookup("alpha", aliases=["Alpha R", "A-Rap"], genres=[("hip hop", 5)]),
        artist_lookup("gamma", genres=[("jazz", 3)], relations=[rel("member of band", "zeta", direction="forward")]),
        artist_lookup(
            "zeta", relations=[rel("member of band", "epsilon", direction="backward"), rel("married", "gamma")]
        ),
        release("alpha-lp", "First Light", credit(("alpha", "", "")), [skyline]),
        release("alpha-deluxe", "First Light (Deluxe)", credit(("alpha", "", "")), [skyline_remaster]),
        release("gamma-lp", "Night Music", credit(("gamma", "", "")), [nocturne]),
        release("theta-lp", "Solitude", credit(("theta", "", "")), [solo]),
    ]
