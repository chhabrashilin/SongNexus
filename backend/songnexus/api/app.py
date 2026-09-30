"""FastAPI application factory.

uvicorn songnexus.api.app:create_app --factory
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from songnexus import __version__
from songnexus.agent.llm import MessagesClient, make_claude_client
from songnexus.api.container import build_container
from songnexus.api.middleware import RequestContextMiddleware
from songnexus.api.routes import router
from songnexus.core.config import Settings, get_settings
from songnexus.core.errors import SongNexusError
from songnexus.core.logging import configure_logging, request_id_var
from songnexus.db.session import create_all, make_engine

log = logging.getLogger(__name__)
_UNSET: object = object()


def _error(status: int, code: str, message: str, details: dict[str, object] | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details or {}, "request_id": request_id_var.get()}}
    return JSONResponse(status_code=status, content=body)


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    llm_client: MessagesClient | object | None = _UNSET,
) -> FastAPI:
    """Build the app. Tests inject settings, an engine, and a fake LLM client."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    engine = engine or make_engine(settings.database_url)
    client = make_claude_client() if llm_client is _UNSET else llm_client
    container = build_container(settings, engine, client)  # type: ignore[arg-type]

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        create_all(engine)
        model = container.store.reload()
        log.info("startup complete", extra={"graph_version": model.version, "llm": container.agent.llm_available})
        yield
        engine.dispose()

    app = FastAPI(
        title="SongNexus API",
        version=__version__,
        description="Music knowledge graph with grounded, provenance-aware discovery.",
        lifespan=lifespan,
    )
    app.state.container = container
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Server-Timing"],
    )

    @app.exception_handler(SongNexusError)
    async def _domain_error(_: Request, exc: SongNexusError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [{"field": ".".join(map(str, e["loc"])), "problem": e["msg"]} for e in exc.errors()]
        return _error(422, "validation_error", "request validation failed", {"problems": problems})

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return _error(500, "internal_error", "an unexpected error occurred")

    app.include_router(router)
    return app
