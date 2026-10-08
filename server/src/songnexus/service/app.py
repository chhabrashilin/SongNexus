"""The FastAPI application: ``create_app`` wires settings, storage and routes.

Run locally with ``uv run uvicorn songnexus.service.app:create_app --factory``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from starlette.concurrency import run_in_threadpool

from songnexus import __version__
from songnexus.config import Settings, get_settings, validate_for_serving
from songnexus.identity.tokens import FirebaseIdTokenVerifier
from songnexus.logs import configure_logging
from songnexus.service.deps import AppState
from songnexus.service.errors import install_error_handlers
from songnexus.service.flags import resolve_flags
from songnexus.service.middleware import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from songnexus.service.ratelimit import MethodClass, RateLimiter
from songnexus.service.readmodel import ReadModelHolder, load_read_model, probe_version
from songnexus.service.routes import analysis, catalog, identity, ops, playlists, users
from songnexus.service.schemas import ErrorResponse
from songnexus.storage.db import make_engine

log = logging.getLogger(__name__)

API_DESCRIPTION = (
    "SongNexus maps the people behind the music and how they connect. Every connection is "
    "backed by evidence with a source. Errors follow AIP-193; lists follow AIP-158."
)


async def _refresh_forever(holder: ReadModelHolder, interval_s: float) -> None:
    while True:
        await asyncio.sleep(interval_s)
        if await run_in_threadpool(holder.refresh):
            log.info("read model reloaded", extra={"version": holder.current().version})


def _openapi_with_error_model(app: FastAPI) -> dict[str, Any]:
    """Returns the OpenAPI document with the real error contract.

    FastAPI documents a 422 validation response that this API never sends;
    every failure is instead the AIP-193 envelope with a canonical status.
    """
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title, version=app.version, description=app.description, routes=app.routes
    )
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for name in ("HTTPValidationError", "ValidationError"):
        components.pop(name, None)
    error_schemas = ErrorResponse.model_json_schema(
        by_alias=True, ref_template="#/components/schemas/{model}"
    )
    components.update(error_schemas.pop("$defs", {}))
    components["ErrorResponse"] = error_schemas
    error_response = {
        "description": "An error (AIP-193): see `error.status` and `error.details[0].reason`.",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
    }
    for path in schema["paths"].values():
        for operation in path.values():
            operation["responses"].pop("422", None)
            operation["responses"]["default"] = error_response
    app.openapi_schema = schema
    return schema


def build_state(settings: Settings) -> AppState:
    """Creates the process-wide state from settings.

    Raises:
        ConfigError: The configuration is unsafe for this environment.
    """
    validate_for_serving(settings, os.environ)
    engine = make_engine(settings.database_url)
    holder = ReadModelHolder(lambda: load_read_model(engine), lambda: probe_version(engine))
    limiter = RateLimiter(
        {
            MethodClass.READ: settings.rate_limit_read_per_minute,
            MethodClass.ANALYZE: settings.rate_limit_analyze_per_minute,
            MethodClass.WRITE: settings.rate_limit_write_per_minute,
        }
    )
    verifier = FirebaseIdTokenVerifier(settings.firebase_project_id)
    return AppState(settings, engine, holder, limiter, verifier, resolve_flags(settings.flags))


def create_app(settings: Settings | None = None, state: AppState | None = None) -> FastAPI:
    """Builds the application.

    Args:
        settings: Configuration (default: from the environment).
        state: Prebuilt state (tests inject one with a fake read model).
    """
    settings = settings or get_settings()
    if state is None:
        configure_logging(settings.log_level, json_output=settings.log_json)
        state = build_state(settings)
    app_state = state

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await run_in_threadpool(app_state.holder.refresh)
        if not app_state.holder.ready:
            log.warning("starting without a catalog; requests get UNAVAILABLE until one loads")
        refresher = asyncio.create_task(
            _refresh_forever(app_state.holder, settings.read_model_refresh_s)
        )
        try:
            yield
        finally:
            refresher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await refresher

    development = settings.environment == "development"
    app = FastAPI(
        title="SongNexus API",
        version=__version__,
        description=API_DESCRIPTION,
        lifespan=lifespan,
        openapi_url="/v1/openapi.json",
        # Operation IDs are the AIP method names (GetArtist, FindPath, ...).
        generate_unique_id_function=lambda route: route.summary or route.name,
        docs_url="/v1/docs" if development else None,
        redoc_url=None,
    )
    app.state.songnexus = app_state
    app.openapi = lambda: _openapi_with_error_model(app)  # type: ignore[method-assign]
    install_error_handlers(app)
    app.include_router(ops.router)
    app.include_router(catalog.router)
    app.include_router(analysis.router)
    app.include_router(playlists.router)
    app.include_router(identity.router)
    app.include_router(users.router)
    # The middleware added last runs outermost, so security headers cover every
    # response, including errors raised by the request-context layer.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RequestContextMiddleware, gcp_project=settings.gcp_project)
    app.add_middleware(SecurityHeadersMiddleware)
    return app
