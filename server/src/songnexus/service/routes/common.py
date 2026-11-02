"""Helpers shared by route modules: limits, DB sessions, caching, path converters."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Request, Response
from sqlalchemy.orm import Session
from starlette.convertors import Convertor, register_url_convertor

from songnexus.core.graph.filters import NodeFilter
from songnexus.core.graph.model import ArtistGraph
from songnexus.service.deps import Viewer, app_state, node_filter
from songnexus.storage.db import session_scope

# The resource name of a catalog artist: artists/{uuid}.
RESOURCE_ID = re.compile(r"^artists/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_QUERY_LENGTH = 120
MAX_PATH_STEPS = 6
MAX_ALTERNATIVES = 3
CATALOG_MAX_AGE_S = 300

Genres = Annotated[list[str], Query(description="Genre resource names to stay within.")]


@dataclass(frozen=True)
class GenreSelection:
    """The genre filter a request asked for."""

    genres: list[str]
    include_unknown_genre: bool
    include_subgenres: bool


def genre_selection(
    genres: Genres = [],  # noqa: B006 - FastAPI copies query defaults
    include_unknown_genre: Annotated[
        bool,
        Query(
            alias="includeUnknownGenre",
            description="Keep artists with no genre data (often producers and session players).",
        ),
    ] = True,
    include_subgenres: Annotated[
        bool,
        Query(alias="includeSubgenres", description="A genre includes the genres below it."),
    ] = True,
) -> GenreSelection:
    """Parses the genre filter parameters shared by graph methods."""
    return GenreSelection(list(genres), include_unknown_genre, include_subgenres)


def selection_filter(viewer: Viewer, selection: GenreSelection, graph: ArtistGraph) -> NodeFilter:
    """Builds the node filter for a genre selection and the viewer's blocks."""
    return node_filter(
        viewer,
        selection.genres,
        include_unknown_genre=selection.include_unknown_genre,
        include_subgenres=selection.include_subgenres,
        graph=graph,
    )


GenreSelectionDep = Annotated[GenreSelection, Depends(genre_selection)]


# AIP-158 list parameters.
PageSize = Annotated[int, Query(alias="pageSize", ge=0, le=1000)]
PageToken = Annotated[str, Query(alias="pageToken", max_length=512)]


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
