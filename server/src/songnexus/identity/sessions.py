"""Session and CSRF tokens (ADR 0002).

The session token is 256 random bits, sent only in an HttpOnly cookie; the
database stores its SHA-256. The CSRF token is derived from the session token
with domain separation, so it needs no storage, changes with every session and
cannot be computed without the cookie, which scripts on other origins never see.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

# Firebase Hosting forwards only a cookie named "__session" to Cloud Run (and
# keys its CDN cache on it); any other name is stripped (ADR 0002, amendment 1).
SESSION_COOKIE = "__session"
CSRF_HEADER = "X-CSRF-Token"
_TOKEN_BYTES = 32


@dataclass(frozen=True)
class NewSession:
    """A freshly minted session token and what derives from it."""

    token: str
    token_hash: str
    csrf_token: str


def hash_token(token: str) -> str:
    """Returns the stored form of a session token."""
    return hashlib.sha256(b"songnexus-session:" + token.encode()).hexdigest()


def csrf_token_for(token: str) -> str:
    """Returns the CSRF token bound to a session token."""
    return hashlib.sha256(b"songnexus-csrf:" + token.encode()).hexdigest()


def new_session() -> NewSession:
    """Mints a new session token."""
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    return NewSession(token, hash_token(token), csrf_token_for(token))


def csrf_matches(token: str, presented: str) -> bool:
    """Checks a presented CSRF token in constant time."""
    return hmac.compare_digest(csrf_token_for(token), presented)
