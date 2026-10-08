"""Structured logging: one JSON object per line, ready for Cloud Logging."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Set per request by the service middleware; attached to every log line.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
# Cloud Logging trace resource ("projects/<p>/traces/<id>"), when known.
trace_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace", default=None)

# Attributes every LogRecord has; anything else was passed via ``extra=``.
_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Formats records as JSON with Cloud Logging's ``severity`` field."""

    def format(self, record: logging.LogRecord) -> str:
        """Returns the record as a single JSON line."""
        payload: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(
            {
                k: v
                for k, v in vars(record).items()
                if k not in _STANDARD_ATTRS and not k.startswith("_")
            }
        )
        if (request_id := request_id_var.get()) is not None:
            payload["requestId"] = request_id
        if (trace := trace_var.get()) is not None:
            payload["logging.googleapis.com/trace"] = trace
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Configures the root logger once, replacing any existing handlers."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        JsonFormatter() if json_output else logging.Formatter("%(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Alembic announces each internal plugin at INFO; the migrations themselves stay visible.
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)
