"""Text normalization shared by ingestion, entity resolution, and search.

A single normalization function is used everywhere so that a name normalized
at ingestion time compares equal to the same name typed into the search box.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# MusicBrainz uses typographic characters (e.g. "JAY‐Z" with U+2010, "Beyoncé").
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
    }
)
_AMPERSAND = re.compile(r"\s*&\s*|\s*\+\s*")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_WS = re.compile(r"\s+")


@lru_cache(maxsize=65536)
def normalize(text: str) -> str:
    """Canonical comparison form: ASCII-folded, lowercase, punctuation-free.

    >>> normalize("Beyoncé")
    'beyonce'
    >>> normalize("JAY‐Z")
    'jay z'
    >>> normalize("Tyler, The Creator")
    'tyler the creator'
    """
    folded = unicodedata.normalize("NFKD", text.translate(_CHAR_FOLDS))
    ascii_only = "".join(ch for ch in folded if not unicodedata.combining(ch))
    lowered = _AMPERSAND.sub(" and ", ascii_only.lower())
    # Apostrophes join rather than split words: "Guns N' Roses" -> "guns n roses".
    lowered = lowered.replace("'", "")
    return _WS.sub(" ", _NON_ALNUM.sub(" ", lowered)).strip()


def name_keys(name: str) -> set[str]:
    """All lookup keys for a name: normalized, article-stripped, and compacted.

    Compaction ("jay z" -> "jayz") lets "jayz" and "Jay-Z" meet; article
    stripping lets "weeknd" find "The Weeknd".
    """
    base = normalize(name)
    if not base:
        return set()
    keys = {base, base.replace(" ", "")}
    if base.startswith("the ") and len(base) > 4:
        stripped = base[4:]
        keys |= {stripped, stripped.replace(" ", "")}
    return keys


def trigrams(text: str) -> set[str]:
    """Character trigrams over a padded, normalized string (pg_trgm-compatible idea)."""
    padded = f"  {text} "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


def trigram_similarity(a: str, b: str) -> float:
    """Jaccard similarity of trigram sets, in [0, 1]."""
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def damerau_levenshtein(a: str, b: str, max_distance: int | None = None) -> int:
    """Optimal-string-alignment edit distance (adjacent transpositions cost 1).

    If ``max_distance`` is given, returns ``max_distance + 1`` as soon as the
    distance is known to exceed it, which bounds the cost for search.
    """
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if max_distance is not None and abs(la - lb) > max_distance:
        return max_distance + 1
    prev_prev: list[int] = []
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        row_min = cur[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev_prev[j - 2] + 1)
            row_min = min(row_min, cur[j])
        if max_distance is not None and row_min > max_distance:
            return max_distance + 1
        prev_prev, prev = prev, cur
    return prev[lb]


def string_similarity(a: str, b: str) -> float:
    """Similarity of two *normalized* strings in [0, 1].

    Combines edit-distance similarity (good for short names and typos) with
    trigram overlap (good for longer names and word reordering).
    """
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    longest = max(len(a), len(b))
    edit_sim = 1.0 - damerau_levenshtein(a, b) / longest
    return max(edit_sim, trigram_similarity(a, b))


# Title decorations that do not change the identity of a song for collaboration
# purposes. Remixes, live and acoustic versions are deliberately NOT stripped:
# they are different works with potentially different credits.
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
    """Strip featuring/remaster/explicit decorations from a track title.

    >>> base_title("Doves in the Wind (feat. Kendrick Lamar)")
    'Doves in the Wind'
    >>> base_title("Hey Jude - Remastered 2015")
    'Hey Jude'
    """
    stripped = _TITLE_DECORATION.sub("", title)
    return _TITLE_DASH_SUFFIX.sub("", stripped).strip() or title.strip()
