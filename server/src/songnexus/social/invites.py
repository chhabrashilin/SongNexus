"""Friend invite codes: the only way to become friends (no search, no contacts).

A code is 10 characters of Crockford base32 (50 random bits), shown as
``XXXXX-XXXXX``. Only its SHA-256 is stored, so a database leak reveals no
usable codes. Reading is forgiving: case, spaces and dashes don't matter, and
the look-alikes O/I/L read as 0/1/1.
"""

from __future__ import annotations

import hashlib
import secrets

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford: no I, L, O, U
CODE_LENGTH = 10
_LOOKALIKES = str.maketrans({"O": "0", "I": "1", "L": "1"})


def new_code() -> str:
    """Returns a fresh code, normalized (no dash)."""
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def display(code: str) -> str:
    """``ABCDE12345`` -> ``ABCDE-12345``."""
    half = CODE_LENGTH // 2
    return f"{code[:half]}-{code[half:]}"


def normalize(raw: str) -> str | None:
    """Returns the canonical code, or None if ``raw`` cannot be one."""
    cleaned = "".join(raw.split()).replace("-", "").upper().translate(_LOOKALIKES)
    if len(cleaned) != CODE_LENGTH or any(ch not in ALPHABET for ch in cleaned):
        return None
    return cleaned


def code_hash(code: str) -> str:
    """The stored form of a normalized code."""
    return hashlib.sha256(code.encode()).hexdigest()
