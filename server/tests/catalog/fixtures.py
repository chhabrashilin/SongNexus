"""Builders for synthetic MusicBrainz raw records (hermetic: no network, no snapshot)."""

from __future__ import annotations

from typing import Any

from songnexus.catalog.snapshot import RawRecord


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


# ---------------------------------------------------------------------------
# Enrichment: the MusicBrainz genre list, Wikidata and Discogs (R2-1)
# ---------------------------------------------------------------------------

# Genre MBIDs for the vocabulary used by the enrichment fixtures.
GENRE_MBIDS = {
    "hip hop": "g-hiphop",
    "trap": "g-trap",
    "jazz": "g-jazz",
    "bebop": "g-bebop",
    "r&b": "g-rnb",
    "funk": "g-funk",
    "soul": "g-soul",
}


def genre_list_record(names: dict[str, str] = GENRE_MBIDS) -> RawRecord:
    return RawRecord(
        kind="genre_list",
        request_key="genre/all?limit=100&offset=0",
        url="https://musicbrainz.test/ws/2/genre/all?limit=100&offset=0&fmt=json",
        retrieved_at="2026-11-01T00:00:00+00:00",
        body={
            "genre-count": len(names),
            "genres": [{"id": mbid, "name": name} for name, mbid in names.items()],
        },
    )


def sparql_record(key: str, rows: list[dict[str, str]]) -> RawRecord:
    return RawRecord(
        kind="sparql",
        request_key=f"?form={key}",
        url="https://query.wikidata.test/sparql",
        retrieved_at="2026-11-01T00:00:00+00:00",
        body={"results": {"bindings": [{k: {"value": v} for k, v in r.items()} for r in rows]}},
    )


def wikidata_records() -> list[RawRecord]:
    """Alice and Bob link to Discogs; trap is a kind of hip hop, bebop a kind of jazz."""
    links = [
        {"item": "Q1", "musicbrainz": "mb-alice", "discogs": "101"},
        {"item": "Q1", "musicbrainz": "mb-alice", "discogs": "102"},  # a second profile
        {"item": "Q2", "musicbrainz": "mb-bob", "discogs": "201"},
    ]
    hierarchy = [
        {"item": "Q10", "genre": "g-trap", "parent": "g-hiphop"},
        {"item": "Q11", "genre": "g-bebop", "parent": "g-jazz"},
        {"item": "Q12", "genre": "g-hiphop"},
        {"item": "Q13", "genre": "g-jazz", "parent": "g-jazz"},  # a self-loop: ignored
    ]
    return [sparql_record("links", links), sparql_record("hierarchy", hierarchy)]


def discogs_record(artist: str, masters: list[dict[str, Any]]) -> RawRecord:
    return RawRecord(
        kind="masters",
        request_key=f"dump/20261001/masters?artist={artist}",
        url="https://data.discogs.test/?download=masters",
        retrieved_at="2026-10-01T00:00:00+00:00",
        body={"artist": artist, "masters": masters},
    )


def master(master_id: str, genres: list[str], styles: list[str]) -> dict[str, Any]:
    return {
        "id": master_id,
        "title": f"Master {master_id}",
        "year": 2001,
        "genres": genres,
        "styles": styles,
    }


def discogs_records() -> list[RawRecord]:
    """Alice: three masters across two profiles (one shared); Bob: one master."""
    return [
        discogs_record(
            "101",
            [master("1", ["Hip Hop"], ["Trap"]), master("2", ["Jazz", "Funk / Soul"], ["Bop"])],
        ),
        discogs_record(
            "102", [master("2", ["Jazz"], []), master("3", ["Hip Hop"], ["Soundtrack"])]
        ),
        discogs_record("201", [master("9", ["Funk / Soul"], ["Contemporary Weirdness"])]),
    ]


# ---------------------------------------------------------------------------
# AcousticBrainz bulk responses (R2-4)
# ---------------------------------------------------------------------------


def acousticbrainz_low(mbid: str, bpm: float, key: str, scale: str) -> dict[str, Any]:
    return {
        "metadata": {"audio_properties": {"length": 201.5}},
        "rhythm": {"bpm": bpm, "danceability": 1.2},
        "tonal": {"key_key": key, "key_scale": scale, "key_strength": 0.6},
        "lowlevel": {"average_loudness": 0.8, "dynamic_complexity": 3.0},
    }


def acousticbrainz_high(happy: float, instrumental: float) -> dict[str, Any]:
    def classifier(name: str, p: float) -> dict[str, Any]:
        return {"all": {name: p, f"not_{name}": 1 - p}, "probability": max(p, 1 - p)}

    return {
        "highlevel": {
            "mood_happy": classifier("happy", happy),
            "voice_instrumental": {
                "all": {"instrumental": instrumental, "voice": 1 - instrumental}
            },
            "gender": {"all": {"female": 0.9, "male": 0.1}},  # present upstream, never kept
        }
    }


def acousticbrainz_responses() -> list[RawRecord]:
    """Bulk responses for rec-1 and rec-2; rec-3 (the remaster) has no data."""
    low = {
        "rec-1": {"0": acousticbrainz_low("rec-1", 96.0, "A", "minor")},
        "rec-2": {"0": acousticbrainz_low("rec-2", 192.5, "C", "major")},
        "mbid_mapping": {},
    }
    high = {
        "rec-1": {"0": acousticbrainz_high(0.7, 0.1)},
        "rec-2": {"0": acousticbrainz_high(0.6, 0.2)},
        "mbid_mapping": {},
    }
    return [
        RawRecord(
            "low-level",
            "low-level?recording_ids=x",
            "https://ab.test/low",
            "2026-11-04T00:00:00+00:00",
            low,
        ),
        RawRecord(
            "high-level",
            "high-level?recording_ids=x",
            "https://ab.test/high",
            "2026-11-04T00:00:00+00:00",
            high,
        ),
    ]


def listenbrainz_records() -> list[RawRecord]:
    """Alice and Bob share an audience; Carol's is too small to describe."""

    def record(mbid: str, body: dict[str, Any]) -> RawRecord:
        return RawRecord(
            "listening",
            f"artist/{mbid}",
            f"https://listenbrainz.org/artist/{mbid}/",
            "2026-11-04T00:00:00+00:00",
            {"artist": mbid, **body},
        )

    return [
        record("mb-alice", {"listeners": 5000, "listens": 90000, "similar": [
            {"artist": "mb-bob", "score": 300, "rank": 3},
            {"artist": "mb-carol", "score": 20, "rank": 60},
        ]}),
        record("mb-bob", {"listeners": 800, "listens": 7000, "similar": [
            {"artist": "mb-alice", "score": 300, "rank": 1},
        ]}),
        record("mb-carol", {"listeners": 12, "listens": 40}),
    ]  # fmt: skip
