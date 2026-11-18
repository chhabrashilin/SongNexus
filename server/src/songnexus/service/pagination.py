"""Opaque page tokens (AIP-158).

A token encodes the offset, the catalog version and a fingerprint of the
request's other parameters. Reusing a token with different parameters, or
after the catalog changed, is rejected rather than returning an inconsistent
page. Tokens are opaque but not secret: forging an offset only skips results.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from songnexus.service.errors import invalid_argument

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def fingerprint(*parts: object) -> str:
    """Returns a short stable hash of the parameters a listing depends on."""
    return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()[:16]


def encode_token(offset: int, version: str, params: str) -> str:
    """Returns the page token for continuing at ``offset``."""
    raw = json.dumps({"o": offset, "v": version, "p": params}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_token(token: str, version: str, params: str) -> int:
    """Returns the offset in ``token``.

    Raises:
        ApiError: INVALID_ARGUMENT when the token is malformed, was issued for
            other parameters, or predates the current catalog version.
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        offset, token_version, token_params = int(data["o"]), str(data["v"]), str(data["p"])
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise invalid_argument("Malformed page token.", field="pageToken") from exc
    if offset < 0 or token_params != params:
        raise invalid_argument(
            "The page token does not match this request's parameters.", field="pageToken"
        )
    if token_version != version:
        raise invalid_argument(
            "The catalog changed since this page token was issued; start again.",
            field="pageToken",
            reason="PAGE_TOKEN_EXPIRED",
        )
    return offset


@dataclass(frozen=True)
class Page[T]:
    """One page of results and the token for the next, if any."""

    items: list[T]
    next_page_token: str
    total_size: int


def paginate[T](
    items: Sequence[T], *, page_size: int, page_token: str, version: str, params: str
) -> Page[T]:
    """Slices ``items`` into the requested page.

    Raises:
        ApiError: INVALID_ARGUMENT for a bad page size or page token.
    """
    if page_size < 0:
        raise invalid_argument("pageSize must not be negative.", field="pageSize")
    size = min(page_size or DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
    offset = decode_token(page_token, version, params) if page_token else 0
    end = offset + size
    next_token = encode_token(end, version, params) if end < len(items) else ""
    return Page(list(items[offset:end]), next_token, len(items))
