"""Operational endpoints: health and client configuration."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from songnexus.service import schemas as api
from songnexus.service.deps import app_state
from songnexus.service.pagination import MAX_PAGE_SIZE
from songnexus.service.routes.common import MAX_ALTERNATIVES, MAX_PATH_STEPS, MAX_QUERY_LENGTH

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
        flags=state.flags,
        limits=api.Limits(
            max_query_length=MAX_QUERY_LENGTH,
            max_path_steps=MAX_PATH_STEPS,
            max_alternatives=MAX_ALTERNATIVES,
            max_page_size=MAX_PAGE_SIZE,
        ),
        graph_version=state.holder.current().version if state.holder.ready else None,
    )
