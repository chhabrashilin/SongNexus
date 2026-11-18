"""Song comparison: the similarity parts, their weights, and shared credits."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from songnexus.core.metrics import roc_auc
from songnexus.core.songs import (
    MOOD_FIELDS,
    Descriptors,
    fifths_position,
    genre_separation,
    key_similarity,
    shared_credits,
    similarity,
    tempo_similarity,
    weight_study,
)


def test_tempo_counts_half_and_double_time_as_the_same_feel() -> None:
    assert tempo_similarity(120, 120) == 1.0
    assert tempo_similarity(70, 140) == pytest.approx(1.0)
    assert tempo_similarity(100, 110) == pytest.approx(0.5)
    assert tempo_similarity(100, 125) == 0.0


def test_keys_use_the_circle_of_fifths_with_relative_minors() -> None:
    def d(key: str, scale: str) -> Descriptors:
        return Descriptors(key=key, scale=scale)

    assert key_similarity(d("C", "major"), d("A", "minor")) == 1.0  # relative keys
    assert key_similarity(d("C", "major"), d("G", "major")) == pytest.approx(5 / 6)
    assert key_similarity(d("C", "major"), d("F#", "major")) == 0.0  # a tritone
    assert key_similarity(d("C", "major"), d("Gb", "major")) == 0.0  # flats too
    assert fifths_position("H", "major") is None
    assert key_similarity(d("C", "major"), Descriptors()) is None


def test_the_score_is_the_weighted_mean_of_the_parts_present() -> None:
    a = Descriptors(bpm=120, key="C", scale="major", moods=dict.fromkeys(MOOD_FIELDS, 0.5))
    b = Descriptors(bpm=120, key="A", scale="minor", moods=dict.fromkeys(MOOD_FIELDS, 0.5))
    result = similarity(a, b)
    assert result.score == pytest.approx(1.0)
    names = [p.name for p in result.parts]
    assert names == ["mood", "tempo", "key"]  # no energy inputs: weights renormalize
    assert sum(p.weight for p in result.parts) == pytest.approx(1.0)
    assert sum(p.contribution for p in result.parts) == pytest.approx(result.score)


def test_no_shared_inputs_means_no_score() -> None:
    assert similarity(Descriptors(bpm=100), Descriptors(key="C", scale="major")).score is None


@given(
    st.lists(st.floats(0, 1), min_size=len(MOOD_FIELDS), max_size=len(MOOD_FIELDS)),
    st.lists(st.floats(0, 1), min_size=len(MOOD_FIELDS), max_size=len(MOOD_FIELDS)),
    st.floats(40, 220),
    st.floats(40, 220),
)
def test_similarity_is_symmetric_and_bounded(
    moods_a: list[float], moods_b: list[float], bpm_a: float, bpm_b: float
) -> None:
    a = Descriptors(bpm=bpm_a, moods=dict(zip(MOOD_FIELDS, moods_a, strict=True)))
    b = Descriptors(bpm=bpm_b, moods=dict(zip(MOOD_FIELDS, moods_b, strict=True)))
    ab, ba = similarity(a, b).score, similarity(b, a).score
    assert ab is not None
    assert ba is not None
    assert 0 <= ab <= 1
    assert ab == pytest.approx(ba)


def test_descriptors_ignore_malformed_fields() -> None:
    d = Descriptors.from_fields({"bpm": "fast", "key": "", "happy": 0.7, "sad": float("nan")})
    assert d.bpm is None
    assert d.key is None
    assert d.moods == {"happy": 0.7}


def test_shared_credits_are_grouped_by_role_shared_first() -> None:
    rows = shared_credits(
        [("p1", "producer"), ("a", "primary"), ("e1", "engineer")],
        [("p1", "producer"), ("b", "primary")],
    )
    assert rows[0].role == "producer"
    assert rows[0].both == ("p1",)
    primary = next(r for r in rows if r.role == "primary")
    assert (primary.only_a, primary.only_b) == (("a",), ("b",))


def test_auc() -> None:
    assert roc_auc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert roc_auc([0.5], [0.5]) == 0.5
    assert roc_auc([], [0.1]) is None


def test_genre_separation_skips_same_artist_pairs_and_ambiguous_ones() -> None:
    loud = Descriptors(bpm=120, moods=dict.fromkeys(MOOD_FIELDS, 0.9))
    soft = Descriptors(bpm=80, moods=dict.fromkeys(MOOD_FIELDS, 0.1))
    recordings = {
        "r1": (loud, "a1", frozenset({"rock"}), "rock"),
        "r2": (loud, "a2", frozenset({"rock"}), "rock"),
        "r3": (soft, "a3", frozenset({"jazz"}), "jazz"),
        "r4": (soft, "a3", frozenset({"jazz"}), "jazz"),  # same artist as r3
    }
    report = genre_separation(recordings, pairs=500, seed=1)
    assert report.recordings == 4
    assert report.auc is not None
    assert report.auc > 0.5  # same-genre pairs sound alike here
    assert report.same_genre_pairs > 0
    assert report.other_pairs > 0


def test_weight_study_fits_on_one_half_and_measures_on_the_other() -> None:
    loud = Descriptors(bpm=120, key="C", scale="major", moods=dict.fromkeys(MOOD_FIELDS, 0.9))
    soft = Descriptors(bpm=120, key="C", scale="major", moods=dict.fromkeys(MOOD_FIELDS, 0.1))
    recordings = {
        f"r{i}": (
            loud if i % 2 else soft,
            f"a{i}",
            frozenset({"g1" if i % 2 else "g2"}),
            "g1" if i % 2 else "g2",
        )
        for i in range(40)
    }
    study = weight_study(recordings, pairs=2000, seed=3)
    # Only mood differs between the genres, so only mood carries signal.
    assert study.fitted["mood"] == 1.0
    assert study.fitted.get("tempo", 0) == 0
    assert study.held_out_fitted is not None
    assert study.held_out_fitted >= (study.held_out_current or 0)
