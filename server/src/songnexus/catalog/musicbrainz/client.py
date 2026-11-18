"""MusicBrainz web-service client: the shared polite client with MusicBrainz's conventions.

MusicBrainz asks for at most one request per second and an identifying
User-Agent (https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting).
Responses are requested as JSON with ``fmt=json``, which is not part of the
request identity.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from songnexus.catalog.http import PoliteClient, SourceRequestError


class MusicBrainzError(SourceRequestError):
    """A MusicBrainz request failed permanently."""


class MusicBrainzClient(PoliteClient):
    """Fetches MusicBrainz web-service responses as ``RawRecord`` values."""

    error_type = MusicBrainzError

    def __init__(
        self,
        *,
        base_url: str,
        cache_dir: Path,
        contact: str = "",
        min_interval_s: float = 1.1,
        max_retries: int = 5,
        http: httpx.Client | None = None,
    ) -> None:
        """Creates a client.

        Args:
            base_url: Web-service root, e.g. ``https://musicbrainz.org/ws/2``.
            cache_dir: Directory for the on-disk response cache.
            contact: Optional contact (URL or address) for the User-Agent, as
                MusicBrainz requests. Empty by default; never defaulted to a
                personal address.
            min_interval_s: Minimum seconds between network requests.
            max_retries: Attempts per request before giving up.
            http: Injected HTTP client (tests use a mock transport).
        """
        super().__init__(
            source="musicbrainz",
            base_url=base_url,
            cache_dir=cache_dir,
            contact=contact,
            min_interval_s=min_interval_s,
            max_retries=max_retries,
            http=http,
        )

    def extra_params(self) -> dict[str, str | int]:
        """Asks for JSON on every request."""
        return {"fmt": "json"}
