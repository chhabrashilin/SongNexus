"""Stages 1-4 (validate -> normalize -> resolve -> canonical rows), no database."""

from __future__ import annotations

from songnexus.core.ids import artist_id_for_mbid
from songnexus.integrations.musicbrainz import parsers as mb
from songnexus.integrations.musicbrainz.snapshot import RawRecord
from songnexus.pipelines.canonicalize import TRACK_MERGE_CONFIDENCE, build_batch
from tests.fixtures import credit, mbid, ref, synthetic_records


def aid(key: str) -> str:
    return artist_id_for_mbid(mbid(key))


def test_split_artist_credit_marks_featured_after_feat_joinphrase() -> None:
    entries = [
        mb.ArtistCreditEntry.model_validate(e)
        for e in credit(("alpha", "", " & "), ("gamma", "", " feat. "), ("beta", "", ""))
    ]
    roles = [role for _, role in mb.split_artist_credit(entries)]
    assert roles == ["primary", "primary", "featured"]


def test_hydrated_artists_are_not_overwritten_by_stub_references() -> None:
    batch = build_batch(synthetic_records())
    alpha = batch.artists[aid("alpha")]
    assert alpha["hydrated"] is True
    assert alpha["begin_date"] == "1990"
    assert batch.artists[aid("delta")]["hydrated"] is False  # known only from credits


def test_credits_capture_performer_and_relationship_roles() -> None:
    batch = build_batch(synthetic_records())
    roles = {(c["artist_id"], c["role"], c["role_detail"]) for c in batch.track_credits.values()}
    assert (aid("alpha"), "primary", "") in roles
    assert (aid("beta"), "featured", "") in roles
    assert (aid("delta"), "producer", "") in roles
    assert (aid("eta"), "engineer", "") in roles
    assert (aid("epsilon"), "instrument", "drums") in roles


def test_remastered_recording_merges_into_one_track_with_lower_confidence_mapping() -> None:
    batch = build_batch(synthetic_records())
    skyline = [t for t in batch.tracks.values() if t["title"] == "Skyline"]
    assert len(skyline) == 1
    mappings = [
        mp for mp in batch.mappings.values() if mp["entity_type"] == "track" and mp["entity_id"] == skyline[0]["id"]
    ]
    assert sorted(mp["decision"] for mp in mappings) == ["created", "merged"]
    assert {mp["confidence"] for mp in mappings} == {1.0, TRACK_MERGE_CONFIDENCE}
    assert batch.stats["recordings_merged"] == 1


def test_relationship_direction_follows_musicbrainz_direction() -> None:
    batch = build_batch(synthetic_records())
    rels = {(r["source_artist_id"], r["target_artist_id"], r["rel_type"]) for r in batch.artist_relationships.values()}
    # Gamma's lookup says gamma -member of band-> zeta (forward).
    assert (aid("gamma"), aid("zeta"), "member_of") in rels
    # Zeta's lookup lists epsilon as a member (backward from zeta's side).
    assert (aid("epsilon"), aid("zeta"), "member_of") in rels
    assert len(rels) == 2


def test_personal_relationships_are_excluded_and_counted() -> None:
    batch = build_batch(synthetic_records())
    assert batch.ignored_relation_types["artist:married"] == 1


def test_credited_as_names_become_aliases_and_self_aliases_are_skipped() -> None:
    batch = build_batch(synthetic_records())
    aliases = {(a["artist_id"], a["alias"], a["alias_type"]) for a in batch.aliases.values()}
    assert (aid("beta"), "B. Singer", "credited_as") in aliases
    assert (aid("alpha"), "Alpha R", "artist_name") in aliases
    assert not any(alias == "Alpha Rapper" for _, alias, _ in aliases)


def test_every_fact_row_points_to_its_raw_record() -> None:
    records = synthetic_records()
    keys = {r.request_key for r in records}
    batch = build_batch(records)
    for table in (batch.track_credits, batch.artist_relationships, batch.aliases, batch.album_tracks):
        assert all(row["_raw_key"] in keys and row["source_id"] == "musicbrainz" for row in table.values())


def test_invalid_record_is_rejected_without_failing_the_batch() -> None:
    broken = RawRecord("release", "release/broken", "https://example.test", "2026-01-01T00:00:00+00:00", {"id": "x"})
    batch = build_batch([*synthetic_records(), broken])
    assert batch.stats["records_rejected"] == 1
    assert batch.rejected[0]["request_key"] == "release/broken"
    assert batch.tracks  # everything else still processed


def test_build_batch_is_deterministic_regardless_of_input_order() -> None:
    records = synthetic_records()
    a = build_batch(records)
    b = build_batch(list(reversed(records)))
    assert a.artists == b.artists
    assert a.track_credits == b.track_credits
    assert a.tracks == b.tracks


def test_stub_reference_fields_fill_gaps_but_do_not_erase() -> None:
    record = RawRecord(
        "release",
        "release/x",
        "https://example.test",
        "2026-01-01T00:00:00+00:00",
        {
            "id": "rel-x",
            "title": "T",
            "artist-credit": [
                {"name": "Delta Producer", "joinphrase": "", "artist": {**ref("delta"), "country": None}}
            ],
            "release-group": {"id": "rg-x", "title": "T", "primary-type": "Album", "first-release-date": "2020"},
            "media": [],
        },
    )
    batch = build_batch([*synthetic_records(), record])
    assert batch.artists[aid("delta")]["country"] == "XX"
