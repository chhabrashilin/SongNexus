"""Text normalization shared by ingestion, entity resolution and search.

One function normalizes names everywhere, so a name normalized at ingestion
compares equal to the same name typed into search, whatever the script.

Design notes:
    * Matching must work across scripts (방탄소년단, Бьорк, 宇多田ヒカル), so
      letters and digits of *every* script are kept. The v0 prototype kept only
      ASCII, which erased non-Latin names entirely.
    * Accents are folded only on Latin, Greek and Cyrillic letters
      ("Beyoncé" -> "beyonce"). Combining marks in other scripts carry meaning
      (Japanese dakuten: カ vs ガ) and are kept.
    * Text is recomposed (NFC) after folding, so Hangul syllables stay whole.
"""

from __future__ import annotations

import functools
import math
import re
import unicodedata
from functools import lru_cache

from rapidfuzz.distance import OSA

# Characters that read as word separators or as letters in music credits.
_CHAR_FOLDS = str.maketrans(
    {
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "×": "x",
        "$": "s",  # "A$AP Rocky" -> "asap rocky", "Ke$ha" -> "kesha"
        "&": " and ",
        "+": " and ",
    }
)
# Accents are stripped only when attached to a base letter below this code point
# (Latin, IPA, Greek, Cyrillic blocks).
_FOLDABLE_BASE_LIMIT = 0x0530
_WS = re.compile(r"\s+")


@lru_cache(maxsize=65536)
def normalize(text: str) -> str:
    """Returns the canonical comparison form of a name.

    Case-folded, accent-folded for Latin/Greek/Cyrillic, punctuation removed,
    whitespace collapsed. Letters and digits of every script are preserved.

    >>> normalize("Beyoncé")
    'beyonce'
    >>> normalize("JAY‐Z")
    'jay z'
    >>> normalize("방탄소년단")
    '방탄소년단'
    """
    # Decompose before case-folding: compatibility characters (e.g. mathematical
    # letters) only become ordinary uppercase letters after NFKD. Decompose again
    # because case-folding can produce precomposed characters.
    folded = unicodedata.normalize("NFKD", text.translate(_CHAR_FOLDS)).casefold()
    decomposed = unicodedata.normalize("NFKD", folded)
    kept: list[str] = []
    base = ""
    for char in decomposed:
        if unicodedata.combining(char):
            if base and ord(base) < _FOLDABLE_BASE_LIMIT:
                continue  # fold the accent off a Latin/Greek/Cyrillic letter
            kept.append(char)
            continue
        base = char
        if char == "'":
            continue  # "Guns N' Roses" -> "guns n roses"
        kept.append(char if char.isalnum() else " ")
    recomposed = unicodedata.normalize("NFC", "".join(kept))
    return _WS.sub(" ", recomposed).strip()


def name_keys(name: str) -> set[str]:
    """Returns every lookup key for a name.

    The normalized form, a compact form without spaces ("jay z" -> "jayz") and,
    for names starting with "the ", the article-free forms ("weeknd").
    """
    base = normalize(name)
    if not base:
        return set()
    keys = {base, base.replace(" ", "")}
    if base.startswith("the ") and len(base) > len("the "):
        stripped = base[len("the ") :]
        keys |= {stripped, stripped.replace(" ", "")}
    return keys


@functools.lru_cache(maxsize=65_536)
def trigrams(text: str) -> frozenset[str]:
    """Returns the character trigrams of a padded string (cached: keys repeat)."""
    padded = f"  {text} "
    return frozenset(padded[i : i + 3] for i in range(len(padded) - 2))


def trigram_similarity(a: str, b: str) -> float:
    """Returns the Jaccard similarity of two strings' trigram sets, in [0, 1]."""
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def damerau_levenshtein(a: str, b: str, max_distance: int | None = None) -> int:
    """Returns the optimal-string-alignment edit distance between two strings.

    Adjacent transpositions cost 1, which models typos well. If ``max_distance``
    is given, returns ``max_distance + 1`` as soon as the distance must exceed it.
    Computed by rapidfuzz (native code); tests check it against a pure-Python
    reference implementation.
    """
    return int(OSA.distance(a, b, score_cutoff=max_distance))


def string_similarity(a: str, b: str, floor: float = 0.0) -> float:
    """Returns the similarity of two normalized strings, in [0, 1].

    The larger of edit-distance similarity (good for short names and typos) and
    trigram similarity (good for long names and reordered words).

    Args:
        a: A normalized string.
        b: Another normalized string.
        floor: Callers that ignore scores below this get the exact score when it
            is at least ``floor`` and some value below ``floor`` otherwise. The
            edit distance is then bounded, which skips most of its cost: search
            scores hundreds of candidates per query.
    """
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    trigram = trigram_similarity(a, b)
    length = max(len(a), len(b))
    # Edit similarity only matters if it can reach max(trigram, floor): that
    # needs distance <= (1 - threshold) * length.
    threshold = max(trigram, floor)
    max_distance = math.floor((1.0 - threshold) * length + 1e-9)
    distance = damerau_levenshtein(a, b, max_distance=max_distance)
    if distance > max_distance:
        return trigram
    return max(1.0 - distance / length, trigram)


# Title decorations that don't change a song's identity for credit purposes.
# Remixes, live and acoustic versions are deliberately kept: they are different
# works with potentially different credits.
_TITLE_DECORATION = re.compile(
    r"""\s*[\(\[]\s*(?:
          (?:feat|ft|featuring|with)\b[^\)\]]*
        | (?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?(?:\s+version)?
        | explicit(?:\s+version)?
        | clean(?:\s+version)?
        | album\s+version
    )\s*[\)\]]""",
    re.IGNORECASE | re.VERBOSE,
)
_TITLE_DASH_SUFFIX = re.compile(r"\s+-\s+(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?\s*$", re.I)


def base_title(title: str) -> str:
    """Strips featuring/remaster/explicit decorations from a track title.

    >>> base_title("Doves in the Wind (feat. Kendrick Lamar)")
    'Doves in the Wind'
    >>> base_title("Hey Jude - Remastered 2015")
    'Hey Jude'
    """
    stripped = _TITLE_DASH_SUFFIX.sub("", _TITLE_DECORATION.sub("", title)).strip()
    return stripped or title.strip()
