import pytest
from hypothesis import given
from hypothesis import strategies as st

from songnexus.core.text import (
    base_title,
    damerau_levenshtein,
    name_keys,
    normalize,
    string_similarity,
    trigram_similarity,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Beyoncé", "beyonce"),
        ("JAY‐Z", "jay z"),  # MusicBrainz uses U+2010 HYPHEN
        ("JAŸ-Z", "jay z"),
        ("Tyler, The Creator", "tyler the creator"),
        ("A$AP Rocky", "asap rocky"),
        ("Anderson .Paak", "anderson paak"),
        ("Simon & Garfunkel", "simon and garfunkel"),
        ("Guns N’ Roses", "guns n roses"),
        ("  Multiple   Spaces ", "multiple spaces"),
        ("", ""),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@given(st.text(max_size=40))
def test_normalize_is_idempotent(text: str) -> None:
    assert normalize(normalize(text)) == normalize(text)


def test_name_keys_include_compact_and_article_free_forms() -> None:
    assert name_keys("The Weeknd") == {"the weeknd", "theweeknd", "weeknd"}
    assert "jayz" in name_keys("JAY-Z")
    assert name_keys("!!!") == set()


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Doves in the Wind (feat. Kendrick Lamar)", "Doves in the Wind"),
        ("Song [ft. Someone]", "Song"),
        ("Song (with Someone)", "Song"),
        ("Hey Jude - Remastered 2015", "Hey Jude"),
        ("Track (2011 Remaster)", "Track"),
        ("Track (Explicit)", "Track"),
        ("Sicko Mode (Remix)", "Sicko Mode (Remix)"),  # remixes are different works
        ("Live at Wembley (Live)", "Live at Wembley (Live)"),
    ],
)
def test_base_title(title: str, expected: str) -> None:
    assert base_title(title) == expected


def test_damerau_levenshtein_counts_transposition_as_one() -> None:
    assert damerau_levenshtein("kendrick", "kendrikc") == 1
    assert damerau_levenshtein("abc", "abc") == 0
    assert damerau_levenshtein("", "abc") == 3


def test_damerau_levenshtein_bounded_early_exit() -> None:
    assert damerau_levenshtein("aaaaaaaa", "bbbbbbbb", max_distance=2) == 3


@given(st.text(alphabet="abcde ", max_size=12), st.text(alphabet="abcde ", max_size=12))
def test_edit_distance_is_symmetric_and_bounded(a: str, b: str) -> None:
    d = damerau_levenshtein(a, b)
    assert d == damerau_levenshtein(b, a)
    assert abs(len(a) - len(b)) <= d <= max(len(a), len(b))


@given(st.text(alphabet="abcdef", min_size=1, max_size=10), st.text(alphabet="abcdef", min_size=1, max_size=10))
def test_similarities_are_in_unit_interval(a: str, b: str) -> None:
    assert 0.0 <= trigram_similarity(a, b) <= 1.0
    assert 0.0 <= string_similarity(a, b) <= 1.0
    assert string_similarity(a, a) == 1.0


def test_similarity_prefers_typo_over_different_name() -> None:
    assert string_similarity("kendrik lamar", "kendrick lamar") > string_similarity("kendrik lamar", "kevin kendrick")
