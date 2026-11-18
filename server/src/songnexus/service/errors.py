"""The API error model (AIP-193): canonical status codes in a Google-style envelope.

Every error response has the shape::

    {
        "error": {
            "code": 404,
            "status": "NOT_FOUND",
            "message": "...",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": "ARTIST_NOT_FOUND",
                    "domain": "songnexus.app",
                    "metadata": {...},
                }
            ],
        }
    }

``message`` is developer-facing English; clients choose user-facing text from
``reason``. Internal errors never leak exception text.
"""

from __future__ import annotations

import enum
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

ERROR_DOMAIN = "songnexus.app"
ERROR_INFO_TYPE = "type.googleapis.com/google.rpc.ErrorInfo"


class Status(enum.Enum):
    """Canonical statuses as (google.rpc.Code number, HTTP status).

    Values are pairs because several statuses share an HTTP code; equal enum
    values would silently become aliases of one another.
    """

    INVALID_ARGUMENT = (3, 400)
    FAILED_PRECONDITION = (9, 400)
    OUT_OF_RANGE = (11, 400)
    UNAUTHENTICATED = (16, 401)
    PERMISSION_DENIED = (7, 403)
    NOT_FOUND = (5, 404)
    ABORTED = (10, 409)
    ALREADY_EXISTS = (6, 409)
    RESOURCE_EXHAUSTED = (8, 429)
    INTERNAL = (13, 500)
    UNAVAILABLE = (14, 503)

    @property
    def http_status(self) -> int:
        """The HTTP status code this canonical status maps to."""
        return int(self.value[1])


class ApiError(Exception):
    """An error with a canonical status, safe to show to API clients."""

    def __init__(
        self,
        status: Status,
        message: str,
        *,
        reason: str,
        metadata: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Creates an error.

        Args:
            status: The canonical status.
            message: Developer-facing explanation, in English.
            reason: Stable UPPER_SNAKE_CASE machine-readable cause.
            metadata: Extra string facts about the cause (e.g. the bad field).
            headers: Extra response headers (e.g. ``Retry-After``).
        """
        super().__init__(message)
        self.status = status
        self.message = message
        self.reason = reason
        self.metadata = metadata or {}
        self.headers = headers or {}


def invalid_argument(message: str, *, field: str, reason: str = "INVALID_ARGUMENT") -> ApiError:
    """Returns an INVALID_ARGUMENT error about one request field."""
    return ApiError(Status.INVALID_ARGUMENT, message, reason=reason, metadata={"field": field})


def not_found(resource_name: str, *, reason: str) -> ApiError:
    """Returns a NOT_FOUND error for a resource name."""
    return ApiError(
        Status.NOT_FOUND,
        f"{resource_name} was not found.",
        reason=reason,
        metadata={"resourceName": resource_name},
    )


def error_body(
    status: Status, message: str, reason: str, metadata: dict[str, str] | None = None
) -> dict[str, Any]:
    """Returns the JSON envelope for an error."""
    return {
        "error": {
            "code": status.http_status,
            "status": status.name,
            "message": message,
            "details": [
                {
                    "@type": ERROR_INFO_TYPE,
                    "reason": reason,
                    "domain": ERROR_DOMAIN,
                    "metadata": metadata or {},
                }
            ],
        }
    }


def _response(
    status: Status,
    message: str,
    reason: str,
    metadata: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        error_body(status, message, reason, metadata),
        status_code=status.http_status,
        headers=headers,
    )


_HTTP_TO_STATUS = {
    400: Status.INVALID_ARGUMENT,
    401: Status.UNAUTHENTICATED,
    403: Status.PERMISSION_DENIED,
    404: Status.NOT_FOUND,
    405: Status.INVALID_ARGUMENT,
    409: Status.ABORTED,
    413: Status.INVALID_ARGUMENT,
    429: Status.RESOURCE_EXHAUSTED,
}


async def _api_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return _response(exc.status, exc.message, exc.reason, exc.metadata, exc.headers)


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    first = exc.errors()[0] if exc.errors() else {}
    location = [str(p) for p in first.get("loc", ())]
    # The first element names where the value came from ("query", "path", ...).
    if location and location[0] in {"query", "path", "body", "header", "cookie"}:
        location = location[1:]
    field = ".".join(location) or "request"
    return _response(
        Status.INVALID_ARGUMENT,
        f"Invalid value for {field}: {first.get('msg', 'invalid')}.",
        "INVALID_ARGUMENT",
        {"field": field},
    )


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    status = _HTTP_TO_STATUS.get(exc.status_code, Status.INTERNAL)
    reasons = {404: "ROUTE_NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
    messages = {404: "No such method.", 405: "This HTTP method is not supported here."}
    reason = reasons.get(exc.status_code, status.name)
    message = messages.get(exc.status_code, str(exc.detail))
    return _response(status, message, reason)


async def _unhandled_error(_request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error", exc_info=exc)
    return _response(Status.INTERNAL, "Internal error.", "INTERNAL")


def install_error_handlers(app: FastAPI) -> None:
    """Routes every failure through the canonical error envelope."""
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled_error)
