"""ASGI middleware: request context and access logs, security headers, HTTP caching.

Written as plain ASGI (not ``BaseHTTPMiddleware``) to avoid per-request task
overhead and to keep streaming responses intact.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable, MutableMapping
from http import HTTPStatus
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


# Anonymous, catalog-only reads that any cache may share. Everything else under /v1 is
# private unless a route says otherwise.
_SHARED_CATALOG = re.compile(
    r"^/v1/(artists[/:]|labels/|recordings/|catalog:search$|genres$|dataSources$)"
)
# Never cacheable, whatever a route sets: personal data, sign-in state, writes' echoes.
_PRIVATE_PREFIXES = (
    "/v1/users",
    "/v1/sessions",
    "/v1/shares",
    "/v1/inbox",
    "/v1/accounts",
    "/v1/oauth",
    "/v1/reports",
    "/v1/blocks",
    "/v1/friends",
    "/v1/invites",
)
SHARED_CACHE_CONTROL = b"public, max-age=60, stale-while-revalidate=600"
PRIVATE_CACHE_CONTROL = b"private, no-store"


def _etag(version: str, method: str, scope: Scope) -> str:
    """A strong validator: catalog version, method and the full request URL."""
    query = scope.get("query_string", b"").decode("latin-1")
    url = f"{scope.get('path', '')}?{query}" if query else str(scope.get("path", ""))
    digest = hashlib.sha256(f"{version}|{method}|{url}".encode()).hexdigest()[:32]
    return f'"{digest}"'


def _matches(if_none_match: str, etag: str) -> bool:
    """True when an ``If-None-Match`` header lists the ETag (weak comparison) or ``*``."""
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    return any(
        candidate.strip().removeprefix("W/") == etag for candidate in if_none_match.split(",")
    )


class CacheHeadersMiddleware:
    """HTTP caching for the API: ETags and 304s for shared catalog reads, no-store otherwise.

    Routes decide whether a response is shareable (``public``: an anonymous
    catalog read; a signed-in viewer's response is ``private, no-store``). This
    layer then:

    * gives shared catalog GETs a strong ETag derived from the catalog version
      and the URL (so a refresh changes every ETag), answers a matching
      ``If-None-Match`` with 304, and sets one cache policy for the whole catalog;
    * forces ``private, no-store`` on personal routes and on any response that
      sets a cookie, whatever a route said;
    * makes every other ``/v1`` response without a policy (errors included)
      ``private, no-store``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handles one ASGI connection."""
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/v1/"):
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET")
        if_none_match = _header(scope, b"if-none-match")
        swallow_body = False

        async def send_with_cache_headers(message: Message) -> None:
            nonlocal swallow_body
            if swallow_body:
                # A 304 has no body: drop the payload, but still end the response.
                if message["type"] == "http.response.body" and not message.get("more_body"):
                    await send({"type": "http.response.body", "body": b""})
                return
            if message["type"] != "http.response.start":
                await send(message)
                return
            headers = [(k, v) for k, v in message.get("headers", ())]
            names = {k.lower() for k, _ in headers}
            policy = next((v for k, v in headers if k.lower() == b"cache-control"), b"")
            status = message["status"]
            private = (
                path.startswith(_PRIVATE_PREFIXES)
                or b"set-cookie" in names
                or policy.startswith(b"private")
            )
            shared = (
                method == "GET"
                and status == HTTPStatus.OK
                and not private
                and _SHARED_CATALOG.match(path) is not None
                and policy.startswith(b"public")
            )
            if shared:
                version = self._version(scope)
                headers = [
                    (k, v) for k, v in headers if k.lower() not in (b"cache-control", b"etag")
                ]
                headers.append((b"cache-control", SHARED_CACHE_CONTROL))
                if version:
                    etag = _etag(version, method, scope)
                    headers.append((b"etag", etag.encode()))
                    if _matches(if_none_match, etag):
                        swallow_body = True
                        headers = [
                            (k, v)
                            for k, v in headers
                            if k.lower() not in (b"content-length", b"content-type")
                        ]
                        await send(
                            {**message, "status": HTTPStatus.NOT_MODIFIED.value, "headers": headers}
                        )
                        return
            elif private or not policy:
                headers = [(k, v) for k, v in headers if k.lower() != b"cache-control"]
                headers.append((b"cache-control", PRIVATE_CACHE_CONTROL))
            message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_cache_headers)

    @staticmethod
    def _version(scope: Scope) -> str:
        """The served catalog version ("" before a catalog loads)."""
        app_state = getattr(scope.get("app"), "state", None)
        holder = getattr(getattr(app_state, "songnexus", None), "holder", None)
        return str(holder.current().version) if holder is not None and holder.ready else ""
