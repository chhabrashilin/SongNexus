"""What to show first: connections a listener will recognize, songs they will know.

Two small, deterministic rankings used where space is short (the connection web,
highlights on a connection). Neither changes the graph or the evidence; both only
order it.

* **Relevance** blends how much two artists made together (connection strength,
  from credits) with how widely known the other artist is (public, aggregate
  ListenBrainz listener counts). An artist with no listener data ranks on
  strength alone, so the blend never hides a strong collaborator; it lifts a
  famous one with fewer credits above a long tail of one-off engineers.
* **Best songs first** puts the shared song a listener most likely knows at the
  front: performances before production credits (the existing kind order), and
  original versions before remixes, live takes, edits and instrumentals.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from typing import Protocol

# How much one order of magnitude of listeners is worth against doubling the
# credits two artists share. At 1.6, an artist with 10x the listeners outranks
# one with about 3x the strength; checked against the dev catalog so that
# headliners appear early without pushing out frequent producers (connection-web-v5.md).
REACH_WEIGHT = 1.6

# Words that mark a recording as a variant of a song, when they appear inside
# brackets or after a dash: "Song (Remix)", "Song - Live at …", "Song [Instrumental]".
_VARIANT_WORDS = (
    r"remix|re-?mix|mix|version|live|instrumental|edit|demo|a ?cappella|acapella|karaoke|"
    r"blend|dub|reprise|remaster(?:ed)?|radio|extended|clean|explicit|sped up|slowed|"
    r"mono|stereo|session|rehearsal|take|interlude|skit|intro|outro"
)
_VARIANT = re.compile(
    rf"(?:[(\[][^)\]]*\b(?:{_VARIANT_WORDS})\b[^)\]]*[)\]])|(?:\s[-–—]\s.*\b(?:{_VARIANT_WORDS})\b)",
    re.IGNORECASE,
)


def relevance(strength: float, listeners: int | None) -> float:
    """Returns a ranking score: higher is shown first.

    Args:
        strength: The connection's strength (weighted credits, >= 0).
        listeners: The other artist's public listener count, or None if unknown.
    """
    reach = math.log10(1 + listeners) if listeners else 0.0
    return math.log2(1 + max(strength, 0.0)) + REACH_WEIGHT * reach


def is_variant_title(title: str | None) -> bool:
    """Whether a recording title names a variant (remix, live, edit…) of a song."""
    return bool(title) and _VARIANT.search(title or "") is not None


class _Titled(Protocol):
    @property
    def subject_title(self) -> str | None: ...


def best_songs_first[T: _Titled](explanations: Iterable[T]) -> list[T]:
    """Reorders explanations so original versions come before variants.

    The sort is stable: within originals and within variants, the given order
    (kind first, then title) is kept, so the result stays deterministic.
    """
    items: Sequence[T] = list(explanations)
    return sorted(items, key=lambda e: is_variant_title(e.subject_title))
