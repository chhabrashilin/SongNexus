"""The moderation hook for text people send each other (share notes, display names).

``Moderator`` is the seam. Locally, ``RuleModerator`` applies a few cheap,
explainable rules: no links (the main spam and phishing vector in notes), no
control or invisible characters, no long runs of one character. Production is
meant to put a toxicity classifier behind the same interface (ADR 0007); until
one is wired, the rules are what runs everywhere, and reports plus blocking
are the backstop.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

_LINK = re.compile(
    r"(https?://|www\.|\b[\w-]+\.(com|net|org|io|ly|gg|xyz|ru|co|me|app|link|info|biz)\b)",
    re.IGNORECASE,
)
_RUN = re.compile(r"(.)\1{9,}")
# Format characters (Cf) include zero-width spaces and bidi overrides used to
# disguise text. The zero-width joiner stays allowed: emoji sequences need it.
_DISALLOWED_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs"})
_ALLOWED_FORMAT = frozenset({"\N{ZERO WIDTH JOINER}"})


@dataclass(frozen=True)
class Verdict:
    """Whether text may be sent, and if not, a machine-readable reason."""

    allowed: bool
    reason: str = ""


ALLOWED = Verdict(allowed=True)


class Moderator(Protocol):
    """Checks a piece of user text before anyone else sees it."""

    def check(self, text: str) -> Verdict:
        """Returns the verdict for ``text``."""
        ...


class RuleModerator:
    """Deterministic rules; the local and fallback moderator."""

    def check(self, text: str) -> Verdict:
        """Rejects links, hidden characters and character floods."""
        if any(
            unicodedata.category(ch) in _DISALLOWED_CATEGORIES and ch not in _ALLOWED_FORMAT
            for ch in text
        ):
            return Verdict(allowed=False, reason="TEXT_HAS_HIDDEN_CHARACTERS")
        if _LINK.search(text):
            return Verdict(allowed=False, reason="TEXT_HAS_LINK")
        if _RUN.search(text):
            return Verdict(allowed=False, reason="TEXT_REJECTED")
        return ALLOWED
