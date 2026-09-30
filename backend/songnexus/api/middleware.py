"""Request correlation, timing, and structured access logging."""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from songnexus.core.logging import request_id_var
from songnexus.core.metrics import metrics

log = logging.getLogger("songnexus.http")
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            route = request.scope.get("route")
            # Route templates (not raw paths) keep metric cardinality bounded.
            route_name = getattr(route, "path", "unmatched")
            metrics.observe(f"http.{request.method} {route_name}", elapsed_ms)
            metrics.counter(f"http.status.{status // 100}xx")
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "route": route_name,
                    "status": status,
                    "elapsed_ms": round(elapsed_ms, 2),
                },
            )
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
        return response
