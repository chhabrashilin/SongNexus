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
        ("STRASSE", "strasse"),
        ("Straße", "strasse"),  # casefold
        ("", ""),
        ("!!!", ""),
    ],
)
def test_normalize_latin(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("방탄소년단", "방탄소년단"),  # Hangul syllables survive (v0 erased them)
        ("宇多田ヒカル", "宇多田ヒカル"),
        ("ガガ", "ガガ"),  # dakuten is meaningful: not folded
        ("Бьорк", "бьорк"),
        ("Björk", "bjork"),
        ("Ελευθερία", "ελευθερια"),
        ("فيروز", "فيروز"),
        ("ＢＴＳ", "bts"),  # full-width compatibility forms
    ],
)
def test_normalize_keeps_every_script(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@given(st.text(max_size=40))
def test_normalize_is_idempotent(text: str) -> None:
    assert normalize(normalize(text)) == normalize(text)


@given(st.text(min_size=1, max_size=40).filter(lambda t: any(c.isalnum() for c in t)))
def test_normalize_never_erases_a_name_with_letters_or_digits(text: str) -> None:
    assert normalize(text) != ""


def test_name_keys() -> None:
    assert name_keys("The Weeknd") == {"the weeknd", "theweeknd", "weeknd"}
    assert "jayz" in name_keys("JAY-Z")
    assert name_keys("!!!") == set()
    assert name_keys("방탄소년단") == {"방탄소년단"}


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Doves in the Wind (feat. Kendrick Lamar)", "Doves in the Wind"),
        ("Song [ft. Someone]", "Song"),
        ("Song (with Someone)", "Song"),
        ("Hey Jude - Remastered 2015", "Hey Jude"),
        ("Track (2011 Remaster)", "Track"),
        ("Track (Explicit)", "Track"),
        ("Sicko Mode (Remix)", "Sicko Mode (Remix)"),
        ("Live at Wembley (Live)", "Live at Wembley (Live)"),
        ("(feat. Someone)", "(feat. Someone)"),  # never strips to nothing
    ],
)
def test_base_title(title: str, expected: str) -> None:
    assert base_title(title) == expected


def test_edit_distance() -> None:
    assert damerau_levenshtein("kendrick", "kendrikc") == 1
    assert damerau_levenshtein("abc", "abc") == 0
    assert damerau_levenshtein("", "abc") == 3
    assert damerau_levenshtein("aaaaaaaa", "bbbbbbbb", max_distance=2) == 3


@given(st.text(alphabet="abcde ", max_size=12), st.text(alphabet="abcde ", max_size=12))
def test_edit_distance_is_a_bounded_symmetric_measure(a: str, b: str) -> None:
    distance = damerau_levenshtein(a, b)
    assert distance == damerau_levenshtein(b, a)
    assert abs(len(a) - len(b)) <= distance <= max(len(a), len(b))


@given(st.text(min_size=1, max_size=10), st.text(min_size=1, max_size=10))
def test_similarities_are_in_unit_interval(a: str, b: str) -> None:
    assert 0.0 <= trigram_similarity(a, b) <= 1.0
    assert 0.0 <= string_similarity(a, b) <= 1.0
    assert string_similarity(a, a) == 1.0


def test_similarity_prefers_typo_over_different_name() -> None:
    assert string_similarity("kendrik lamar", "kendrick lamar") > string_similarity(
        "kendrik lamar", "kevin kendrick"
    )
