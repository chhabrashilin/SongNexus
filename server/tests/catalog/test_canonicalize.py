from songnexus.catalog.canonicalize import (
    RECORDING_MERGE_CONFIDENCE,
    SOURCE_ID,
    SUPPLEMENTARY_SOURCE_ID,
    build_batch,
)
from songnexus.catalog.musicbrainz.parsers import ArtistCreditEntry, split_artist_credit
from songnexus.catalog.musicbrainz.snapshot import RawRecord
from songnexus.core import ids
from songnexus.core.model import CreditRole
from tests.catalog import fixtures as fx

ALICE = ids.artist_id("mb-alice")
BOB = ids.artist_id("mb-bob")
BAND = ids.artist_id("mb-band")
CAROL = ids.artist_id("mb-carol")


def _roles(*entries: tuple[str, str, str]) -> list[CreditRole]:
    parsed = [ArtistCreditEntry.model_validate(e) for e in fx.credit(*entries)]
    return [role for _, role in split_artist_credit(parsed)]


def test_artist_credit_featuring_split() -> None:
    assert _roles(("a", "A", " & "), ("b", "B", " feat. "), ("c", "C", "")) == [
        CreditRole.PRIMARY,
        CreditRole.PRIMARY,
        CreditRole.FEATURED,
    ]
    assert _roles(("a", "A", " ft "), ("b", "B", ", "), ("c", "C", "")) == [
        CreditRole.PRIMARY,
        CreditRole.FEATURED,
        CreditRole.FEATURED,
    ]
    # "with" is a featuring join phrase; "x" is a co-primary one.
    assert _roles(("a", "A", " with "), ("b", "B", "")) == [CreditRole.PRIMARY, CreditRole.FEATURED]
    assert _roles(("a", "A", " x "), ("b", "B", "")) == [CreditRole.PRIMARY, CreditRole.PRIMARY]


def test_remaster_is_deduplicated_into_one_recording() -> None:
    batch = build_batch(fx.small_catalog())
    titles = sorted(r["title"] for r in batch.recordings.values())
    assert titles == ["Other Song", "Song"]
    merged = [m for m in batch.mappings.values() if m["decision"] == "merged"]
    assert len(merged) == 1
    assert merged[0]["source_entity_id"] == "rec-3"
    assert merged[0]["confidence"] == RECORDING_MERGE_CONFIDENCE
    assert batch.stats["recordings_merged"] == 1


def test_credits_have_roles_and_credited_names() -> None:
    batch = build_batch(fx.small_catalog())
    song = next(r["id"] for r in batch.recordings.values() if r["title"] == "Song")
    roles = {
        (c["artist_id"], c["role"])
        for c in batch.recording_credits.values()
        if c["recording_id"] == song
    }
    assert roles == {(ALICE, "primary"), (BOB, "featured"), (CAROL, "producer")}


def test_relation_direction_and_ignored_personal_relations() -> None:
    batch = build_batch(fx.small_catalog())
    (relation,) = batch.artist_relations.values()
    assert (
        relation["subject_artist_id"],
        relation["relation_type"],
        relation["object_artist_id"],
    ) == (
        ALICE,
        "member_of",
        BAND,
    )
    assert batch.ignored_relation_types["artist:married"] == 1


def test_backward_relation_is_flipped() -> None:
    member = fx.artist_ref("mb-alice", "Alice")
    record = fx.artist_record(
        "mb-band", "The Band", relations=[fx.artist_rel("member of band", member, "backward")]
    )
    (relation,) = build_batch([record]).artist_relations.values()
    assert (relation["subject_artist_id"], relation["object_artist_id"]) == (ALICE, BAND)


def test_only_known_link_types_are_kept() -> None:
    batch = build_batch(fx.small_catalog())
    assert [link["url"] for link in batch.links.values()] == ["https://alice.example"]


def test_genres_are_attributed_to_the_supplementary_source() -> None:
    batch = build_batch(fx.small_catalog())
    assert {g["normalized_name"] for g in batch.genres.values()} == {"hip hop", "jazz", "r and b"}
    assert {f["source_id"] for f in batch.artist_genres.values()} == {SUPPLEMENTARY_SOURCE_ID}
    other_facts = [
        *batch.aliases.values(),
        *batch.recording_credits.values(),
        *batch.links.values(),
    ]
    assert {f["source_id"] for f in other_facts} == {SOURCE_ID}


def test_labels_keep_the_smallest_catalog_number() -> None:
    batch = build_batch(fx.small_catalog())
    (label,) = batch.labels.values()
    assert label["name"] == "Label Records"
    (release_label,) = batch.release_labels.values()
    assert release_label["catalog_number"] == "LR-001"


def test_detail_levels_never_downgrade() -> None:
    batch = build_batch(fx.small_catalog())
    assert batch.artists[ALICE]["detail_level"] == "full"
    assert batch.artists[BOB]["detail_level"] == "profile"
    assert batch.artists[CAROL]["detail_level"] == "stub"


def test_non_latin_alias_is_kept_and_credited_as_skipped_when_identical() -> None:
    batch = build_batch(fx.small_catalog())
    aliases = {(a["artist_id"], a["alias"], a["alias_type"]) for a in batch.aliases.values()}
    assert (ALICE, "アリス", "artist_name") in aliases
    assert not any(alias == "Alice" for _, alias, _ in aliases)


def test_malformed_record_is_rejected_not_fatal() -> None:
    bad = RawRecord("release", "release/bad", "u", "t", {"id": "bad"})
    batch = build_batch([*fx.small_catalog(), bad])
    assert [r["requestKey"] for r in batch.rejected] == ["release/bad"]
    assert len(batch.releases) == 2


def test_build_is_deterministic_regardless_of_input_order() -> None:
    records = fx.small_catalog()
    forward, backward = build_batch(records), build_batch(list(reversed(records)))
    assert forward.artists == backward.artists
    assert forward.recording_credits == backward.recording_credits
    assert forward.mappings == backward.mappings


def test_partial_dates_are_normalized() -> None:
    from songnexus.catalog.canonicalize import partial_date

    assert partial_date("1999") == "1999"
    assert partial_date("1999-07") == "1999-07"
    assert partial_date("1999-07-04") == "1999-07-04"
    assert partial_date("????-12-23") is None
    assert partial_date("") is None
    assert partial_date(None) is None
    record = fx.artist_record("mb-x", "X")
    body = {**record.body, "life-span": {"begin": "????-12-23", "end": "2001-??"}}
    batch = build_batch([RawRecord("artist", "artist/mb-x", "u", "t", body)])
    artist = batch.artists[ids.artist_id("mb-x")]
    assert (artist["begin_date"], artist["end_date"]) == (None, None)
