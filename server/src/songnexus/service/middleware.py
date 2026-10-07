"""ASGI middleware: request context and access logs, and security headers.

Written as plain ASGI (not ``BaseHTTPMiddleware``) to avoid per-request task
overhead and to keep streaming responses intact.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from songnexus.logs import request_id_var, trace_var
from songnexus.service.errors import Status, error_body

log = logging.getLogger("songnexus.http")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_TRACE_HEADER = re.compile(r"^([0-9a-f]{32})(?:/\d+)?(?:;o=\d)?$")

# An API serves JSON only, so its policy can forbid everything.
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    (b"strict-transport-security", b"max-age=63072000; includeSubDomains"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-resource-policy", b"same-origin"),
)


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", ()):
        if key == name:
            return str(value.decode("latin-1"))
    return ""


class RequestContextMiddleware:
    """Assigns a request ID, links the Cloud Trace context, and logs each request.

    Logs carry the route template (never the raw path, which could hold
    personal data in a query) and never the query string.
    """

    def __init__(self, app: ASGIApp, *, gcp_project: str = "") -> None:
        self.app = app
        self.gcp_project = gcp_project

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handles one ASGI connection."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = _header(scope, b"x-request-id")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else secrets.token_hex(8)
        trace_match = _TRACE_HEADER.match(_header(scope, b"x-cloud-trace-context"))
        trace = (
            f"projects/{self.gcp_project}/traces/{trace_match.group(1)}"
            if trace_match and self.gcp_project
            else None
        )
        request_token, trace_token = request_id_var.set(request_id), trace_var.set(trace)
        started = time.perf_counter()
        status = 500

        async def send_with_context(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                elapsed_ms = (time.perf_counter() - started) * 1000
                headers = list(message.get("headers", ()))
                headers.append((b"x-request-id", request_id.encode()))
                headers.append((b"server-timing", f"app;dur={elapsed_ms:.1f}".encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        finally:
            route = scope.get("route")
            log.info(
                "request",
                extra={
                    "httpMethod": scope.get("method"),
                    "route": getattr(route, "path", "unmatched"),
                    "status": status,
                    "latencyMs": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            request_id_var.reset(request_token)
            trace_var.reset(trace_token)


# The interactive API docs (development only) load Swagger UI from a CDN.
_DOCS_PATHS = ("/v1/docs", "/v1/openapi.json")


class SecurityHeadersMiddleware:
    """Adds security headers to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handles one ASGI connection."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", ())}
                if scope.get("path", "").startswith(_DOCS_PATHS):
                    existing.add(b"content-security-policy")
                message["headers"] = [
                    *message.get("headers", ()),
                    *(h for h in SECURITY_HEADERS if h[0] not in existing),
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)


MAX_BODY_BYTES = 1024 * 1024  # plan §14: payloads ≤ 1 MB


class BodySizeLimitMiddleware:
    """Rejects request bodies over a limit before they reach the application.

    A declared ``Content-Length`` is checked up front (the HTTP server enforces
    that the body matches it). A body without one (chunked) is buffered up to the
    limit, at most ``max_bytes`` of memory, and replayed to the application.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handles one ASGI connection."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _header(scope, b"content-length")
        if declared:
            if not declared.isdigit() or int(declared) > self.max_bytes:
                await self._reject(send)
                return
            await self.app(scope, receive, send)
            return

        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                await self._reject(send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(self, send: Send) -> None:
        body = json.dumps(
            error_body(
                Status.INVALID_ARGUMENT,
                f"The request body exceeds {self.max_bytes} bytes.",
                "REQUEST_TOO_LARGE",
            )
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": Status.INVALID_ARGUMENT.http_status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
