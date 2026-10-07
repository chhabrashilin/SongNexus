"""Builders for synthetic MusicBrainz raw records (hermetic: no network, no snapshot)."""

from __future__ import annotations

from typing import Any

from songnexus.catalog.musicbrainz.snapshot import RawRecord


def artist_ref(mbid: str, name: str, **extra: Any) -> dict[str, Any]:
    return {"id": mbid, "name": name, "sort-name": name, "type": "Person", **extra}


def credit(*entries: tuple[str, str, str]) -> list[dict[str, Any]]:
    """Builds an artist credit from (mbid, name, joinphrase) tuples."""
    return [
        {"name": name, "joinphrase": join, "artist": artist_ref(mbid, name)}
        for mbid, name, join in entries
    ]


def artist_rel(
    rel_type: str, other: dict[str, Any], direction: str = "forward", **extra: Any
) -> dict[str, Any]:
    return {
        "type": rel_type,
        "direction": direction,
        "target-type": "artist",
        "artist": other,
        "attributes": extra.pop("attributes", []),
        **extra,
    }


def url_rel(rel_type: str, url: str) -> dict[str, Any]:
    return {
        "type": rel_type,
        "direction": "forward",
        "target-type": "url",
        "url": {"resource": url},
    }


def artist_record(
    mbid: str,
    name: str,
    *,
    kind: str = "artist",
    aliases: list[dict[str, Any]] | None = None,
    genres: list[dict[str, Any]] | None = None,
    relations: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> RawRecord:
    body = {
        **artist_ref(mbid, name, **extra),
        "life-span": {"begin": "1990"},
        "aliases": aliases or [],
        "genres": genres or [],
        "relations": relations or [],
    }
    return RawRecord(
        kind=kind,
        request_key=f"artist/{mbid}?inc={kind}",
        url=f"https://musicbrainz.test/ws/2/artist/{mbid}",
        retrieved_at="2026-10-01T00:00:00+00:00",
        body=body,
    )


def recording(
    mbid: str,
    title: str,
    artist_credit: list[dict[str, Any]],
    *,
    length: int | None = 200_000,
    relations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": mbid,
        "title": title,
        "length": length,
        "first-release-date": "2020-01-01",
        "artist-credit": artist_credit,
        "relations": relations or [],
    }


def release_record(
    mbid: str,
    group_mbid: str,
    title: str,
    artist_credit: list[dict[str, Any]],
    recordings: list[dict[str, Any]],
    *,
    labels: list[dict[str, Any]] | None = None,
    relations: list[dict[str, Any]] | None = None,
) -> RawRecord:
    body = {
        "id": mbid,
        "title": title,
        "date": "2020-01-01",
        "artist-credit": artist_credit,
        "release-group": {
            "id": group_mbid,
            "title": title,
            "primary-type": "Album",
            "first-release-date": "2020-01-01",
        },
        "media": [
            {
                "position": 1,
                "tracks": [
                    {"id": f"{mbid}-t{i}", "position": i, "title": r["title"], "recording": r}
                    for i, r in enumerate(recordings, start=1)
                ],
            }
        ],
        "label-info": labels or [],
        "relations": relations or [],
    }
    return RawRecord(
        kind="release",
        request_key=f"release/{mbid}",
        url=f"https://musicbrainz.test/ws/2/release/{mbid}",
        retrieved_at="2026-10-01T00:00:00+00:00",
        body=body,
    )


def label_info(mbid: str, name: str, catalog_number: str | None = None) -> dict[str, Any]:
    return {
        "catalog-number": catalog_number,
        "label": {"id": mbid, "name": name, "type": "Original Production"},
    }


def small_catalog() -> list[RawRecord]:
    """A tiny but realistic catalog: two seed artists, a band, a collaboration.

    Alice (seed) is a member of The Band; Bob (seed) features on Alice's song;
    Carol produced it. Alice's song appears twice (original and remaster) to
    exercise deduplication. Alice has a Japanese alias and genre tags.
    """
    band = artist_ref("mb-band", "The Band", type="Group")
    carol = artist_ref("mb-carol", "Carol")
    alice_feat_bob = credit(("mb-alice", "Alice", " feat. "), ("mb-bob", "Bob", ""))
    return [
        artist_record(
            "mb-alice",
            "Alice",
            aliases=[{"name": "アリス", "type": "Artist name", "locale": "ja"}],
            genres=[{"name": "Hip-Hop", "count": 5}, {"name": "jazz", "count": 2}],
            relations=[
                artist_rel("member of band", band),
                url_rel("official homepage", "https://alice.example"),
                url_rel("lyrics", "https://ignored.example"),
                artist_rel("married", carol),  # personal relation: ignored
            ],
        ),
        artist_record("mb-bob", "Bob", kind="artist_profile", genres=[{"name": "R&B", "count": 1}]),
        release_record(
            "rel-1",
            "rg-1",
            "First Album",
            credit(("mb-alice", "Alice", "")),
            [
                recording(
                    "rec-1",
                    "Song",
                    alice_feat_bob,
                    relations=[artist_rel("producer", carol)],
                ),
                recording("rec-2", "Other Song", credit(("mb-alice", "Alice", ""))),
            ],
            labels=[
                label_info("mb-label", "Label Records", "LR-002"),
                label_info("mb-label", "Label Records", "LR-001"),
            ],
        ),
        release_record(
            "rel-2",
            "rg-2",
            "Best Of",
            credit(("mb-alice", "Alice", "")),
            [recording("rec-3", "Song (2020 Remaster)", alice_feat_bob)],
        ),
    ]
