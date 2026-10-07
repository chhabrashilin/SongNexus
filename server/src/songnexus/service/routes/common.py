"""Helpers shared by route modules: limits, DB sessions, caching, path converters."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request, Response
from sqlalchemy.orm import Session
from starlette.convertors import Convertor, register_url_convertor

from songnexus.service.deps import Viewer, app_state
from songnexus.storage.db import session_scope

MAX_QUERY_LENGTH = 120
MAX_PATH_STEPS = 6
MAX_ALTERNATIVES = 3
CATALOG_MAX_AGE_S = 300


class ResourceIdConvertor(Convertor[str]):
    """Matches one path segment without ':' so custom methods (``:findPath``) route."""

    regex = "[^/:]+"

    def convert(self, value: str) -> str:
        """Returns the segment unchanged (validated by the handler)."""
        return value

    def to_string(self, value: str) -> str:
        """Returns the segment unchanged."""
        return value


register_url_convertor("rid", ResourceIdConvertor())


def db_session(request: Request) -> Iterator[Session]:
    """Yields a session for one request.

    Use with ``Depends(db_session, scope="function")``: the commit then happens
    before the response is sent, so a failed commit is an error response, never
    a false success (QA review Q2).
    """
    with session_scope(app_state(request).engine) as session:
        yield session


def set_cache_control(response: Response, viewer: Viewer | None) -> None:
    """Marks a catalog response cacheable by shared caches unless it is personal."""
    if viewer is not None and viewer.personalized:
        response.headers["Cache-Control"] = "private, no-store"
    else:
        response.headers["Cache-Control"] = f"public, max-age={CATALOG_MAX_AGE_S}"
        response.headers["Vary"] = "Cookie"
