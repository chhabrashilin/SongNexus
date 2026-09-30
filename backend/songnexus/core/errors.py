"""Domain errors. The API layer maps these to a single consistent error envelope."""

from __future__ import annotations

from typing import Any


class SongNexusError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(SongNexusError):
    status_code = 404
    code = "not_found"


class InvalidRequestError(SongNexusError):
    status_code = 400
    code = "invalid_request"


class GraphUnavailableError(SongNexusError):
    status_code = 503
    code = "graph_unavailable"


class RateLimitedError(SongNexusError):
    status_code = 429
    code = "rate_limited"
