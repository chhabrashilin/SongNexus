"""Operational endpoints: health, client configuration and the data-source registry."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Request, Response

from songnexus.catalog.sources import SOURCES
from songnexus.service import schemas as api
from songnexus.service.deps import app_state
from songnexus.service.pagination import MAX_PAGE_SIZE, paginate
from songnexus.service.routes.common import (
    MAX_ALTERNATIVES,
    MAX_PATH_STEPS,
    MAX_QUERY_LENGTH,
    PageSize,
    PageToken,
)
from songnexus.service.routes.identity import local_sign_in_enabled

# Page tokens are tied to the registry contents, so a deploy that edits it invalidates old tokens.
_SOURCES_VERSION = hashlib.sha256(repr(SOURCES).encode()).hexdigest()[:12]

router = APIRouter(tags=["ops"])


@router.get("/healthz", response_model=api.Health, summary="Health")
def healthz(request: Request, response: Response) -> api.Health:
    """Liveness: the process is up. Reports whether the catalog is loaded (readiness)."""
    response.headers["Cache-Control"] = "no-store"
    return api.Health(status="ok", catalog_loaded=app_state(request).holder.ready)


@router.get("/v1/config", response_model=api.Config, summary="GetConfig")
def get_config(request: Request, response: Response) -> api.Config:
    """Returns feature flags and request limits for the client."""
    state = app_state(request)
    response.headers["Cache-Control"] = "public, max-age=60"
    return api.Config(
        flags={**state.flags, "localSignIn": local_sign_in_enabled(state.settings)},
        limits=api.Limits(
            max_query_length=MAX_QUERY_LENGTH,
            max_path_steps=MAX_PATH_STEPS,
            max_alternatives=MAX_ALTERNATIVES,
            max_page_size=MAX_PAGE_SIZE,
        ),
        graph_version=state.holder.current().version if state.holder.ready else None,
    )


@router.get(
    "/v1/dataSources", response_model=api.ListDataSourcesResponse, summary="ListDataSources"
)
def list_data_sources(
    response: Response, page_size: PageSize = 100, page_token: PageToken = ""
) -> api.ListDataSourcesResponse:
    """Lists every data source SongNexus uses or evaluates, with its license (the registry)."""
    page = paginate(
        SOURCES,
        page_size=page_size,
        page_token=page_token,
        version=_SOURCES_VERSION,
        params="dataSources",
    )
    response.headers["Cache-Control"] = "public, max-age=3600"
    return api.ListDataSourcesResponse(
        data_sources=[
            api.DataSource(
                name=f"dataSources/{s.id}",
                display_name=s.name,
                homepage=s.homepage,
                license=s.license,
                license_url=s.license_url,
                tier=api.LicenseTier(s.tier),
                status=api.SourceStatus(s.status),
                kind=api.SourceKind(s.kind),
                feeds=list(s.feeds),
                attribution=s.attribution,
                checked_on=s.checked_on,
                notes=s.notes,
            )
            for s in page.items
        ],
        next_page_token=page.next_page_token,
        total_size=page.total_size,
    )
