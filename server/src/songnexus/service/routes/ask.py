"""AskCatalog (ADR 0008): a question from the search bar, answered from our data.

The model (when configured) only interprets the question; the parser does so
without one. Names are resolved against the catalog and the answer is composed
from the graph and credits, with evidence and sources, so nothing in the
response comes from the model except the reading of the question.

Privacy: only the question text goes to the model. Logs carry the intent,
outcome and latency, never the question.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from songnexus.core.ask import answer as core
from songnexus.core.ask.intents import Intent, Interpretation, Source
from songnexus.core.ask.interpreter import (
    CACHE_TTL_S,
    Interpreted,
    Interpreter,
    ModelOutcome,
    Store,
)
from songnexus.core.ask.llm import make_provider
from songnexus.core.ask.resolve import Candidate, Resolved, genre_vocabulary
from songnexus.core.search import EntityType
from songnexus.core.songs import Descriptors, similarity
from songnexus.service import convert
from songnexus.service import schemas as api
from songnexus.service import schemas_ask as ask
from songnexus.service.deps import (
    Viewer,
    app_state,
    parse_name,
    rate_limited,
    read_model,
    viewer,
)
from songnexus.service.errors import ApiError, Status, invalid_argument
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes.common import db_session
from songnexus.storage import catalog_repository as repo

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1", tags=["catalog"], dependencies=[Depends(rate_limited(MethodClass.ANALYZE))]
)

ModelDep = Annotated[ReadModel, Depends(read_model)]
ViewerDep = Annotated[Viewer, Depends(viewer)]
SessionDep = Annotated[Session, Depends(db_session, scope="function")]

_INTERPRETER_LOCK = threading.Lock()
_COLLECTIONS = {EntityType.ARTIST: "artists", EntityType.RECORDING: "recordings"}


def interpreter(request: Request) -> Interpreter:
    """The process's interpreter, built from settings on first use (tests may preset one)."""
    existing: Interpreter | None = getattr(request.app.state, "ask_interpreter", None)
    if existing is not None:
        return existing
    with _INTERPRETER_LOCK:
        existing = getattr(request.app.state, "ask_interpreter", None)
        if existing is None:
            settings = app_state(request).settings
            timeout = httpx.Timeout(
                settings.llm_timeout_s, connect=min(2.0, settings.llm_timeout_s)
            )
            provider = make_provider(
                settings.llm_provider,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
                base_url=settings.llm_base_url,
                http_factory=lambda: httpx.Client(timeout=timeout),
            )
            existing = Interpreter(provider)
            request.app.state.ask_interpreter = existing
            log.info(
                "ask interpreter ready",
                extra={
                    "provider": provider.name if provider else "none",
                    "model": provider.model if provider else "",
                },
            )
    return existing


class _SharedStore:
    """Adapts the service response cache (memory, optional Redis, single-flight)."""

    def __init__(self, cache: object) -> None:
        self._cache = cache

    def get_or_compute(self, key: str, compute: Callable[[], bytes]) -> tuple[bytes, bool]:
        found = self._cache.get_or_compute(key, compute, ttl_s=CACHE_TTL_S)  # type: ignore[attr-defined]
        return found.value, found.source != "miss"


class _DatabaseCatalog:
    """Recording credits and descriptors for answers, read from the catalog database."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def recording(self, recording_id: str) -> core.RecordingFacts | None:
        details = repo.recording_details(self._session, recording_id)
        if details is None:
            return None
        return core.RecordingFacts(
            details.id, details.title, tuple((c.artist_id, c.role) for c in details.credits)
        )

    def song_similarity(self, a: str, b: str) -> float | None:
        fields = [repo.recording_descriptors(self._session, x) for x in (a, b)]
        if fields[0] is None or fields[1] is None:
            return None
        return similarity(
            Descriptors.from_fields(fields[0]), Descriptors.from_fields(fields[1])
        ).score


def _choices(values: list[str]) -> frozenset[str]:
    ids = set()
    for value in values:
        collection = "recordings" if value.startswith("recordings/") else "artists"
        ids.add(parse_name(value, collection, field="choices"))
    return frozenset(ids)


def _candidate(c: Candidate) -> ask.AskCandidate:
    return ask.AskCandidate(
        name=f"{_COLLECTIONS[c.entity_type]}/{c.entity_id}",
        display_name=c.name,
        subtitle=c.subtitle,
    )


def _entity(e: Resolved) -> ask.AskEntity:
    return ask.AskEntity(
        mention=e.mention,
        entity_type=e.entity_type.value.upper(),
        status=ask.EntityStatus(e.status.value),
        match=_candidate(e.match) if e.match else None,
        alternatives=[_candidate(c) for c in e.alternatives],
    )


def _interpretation(found: Interpretation | None, result: core.Answer) -> ask.AskInterpretation:
    by = (
        ask.InterpretedBy.NONE
        if found is None or result.intent is Intent.UNKNOWN
        else ask.InterpretedBy.MODEL
        if found.source is Source.MODEL
        else ask.InterpretedBy.PARSER
    )
    narrowing = found if found is not None and found.intent is result.intent else None
    return ask.AskInterpretation(
        intent=ask.AskIntent(result.intent.value),
        interpreted_by=by,
        credit_role=(
            ask.AskCreditRole(narrowing.credit_role.value)
            if narrowing and narrowing.credit_role
            else None
        ),
        collaboration_type=(
            api.CollaborationType(narrowing.collaboration_type.value)
            if narrowing and narrowing.collaboration_type
            else None
        ),
        direction=(
            api.ProductionDirection(narrowing.direction.value)
            if narrowing and narrowing.direction
            else None
        ),
        start_year=narrowing.start_year if narrowing else None,
        end_year=narrowing.end_year if narrowing else None,
        genre=f"genres/{result.genre[0]}" if result.genre else None,
        genre_display_name=result.genre[1] if result.genre else None,
        strongest=bool(found and found.strongest),
    )


def _rows(result: core.Answer, model: ReadModel, session: Session) -> list[ask.AskRow]:
    graph = model.graph
    sources = repo.subject_sources(session, core.subjects_of(result.rows))
    recording_sources = {
        r.credited_on: repo.recording_details(session, r.credited_on)
        for r in result.rows
        if r.credited_on
    }
    rows = []
    for row in result.rows:
        details = recording_sources.get(row.credited_on) if row.credited_on else None
        rows.append(
            ask.AskRow(
                artist=convert.artist_summary(graph, row.artist_id) if row.artist_id else None,
                recording=_candidate(row.recording) if row.recording else None,
                role=row.role,
                count=row.count,
                first_year=row.first_year,
                last_year=row.last_year,
                evidence=[convert.evidence(e, sources) for e in row.explanations],
                sources=convert.source_links(details.sources) if details else [],
            )
        )
    return rows


def _log(interpreted: Interpreted, result: core.Answer, started: float) -> None:
    log.info(
        "ask",
        extra={
            "metric": "ask",
            "intent": result.intent.value,
            "answer": result.message_id,
            "modelOutcome": interpreted.model_outcome.value,
            "modelMs": interpreted.model_ms,
            "modelFailure": interpreted.failure,
            "latencyMs": round((time.perf_counter() - started) * 1000, 1),
        },
    )


@router.post("/catalog:ask", response_model=ask.AskResponse, summary="AskCatalog")
def ask_catalog(
    body: ask.AskRequest,
    request: Request,
    response: Response,
    model: ModelDep,
    who: ViewerDep,
    session: SessionDep,
) -> ask.AskResponse:
    """Answers a question about credits and connections from the catalog.

    The question is read by the built-in parser or, when the parser can't
    place it and a model is configured, by the model, which only picks one of
    the fixed intents and copies names from the question. Every fact in the
    answer comes from the catalog, with evidence and sources. Ambiguous names
    are returned with alternatives; send a pick back in ``choices``.
    """
    started = time.perf_counter()
    if not app_state(request).flags.get("ask", True):
        raise ApiError(Status.UNAVAILABLE, "Ask is switched off.", reason="FLAG_OFF")
    query = body.query.strip()
    if not query:
        raise invalid_argument("query must not be blank.", field="query")
    choices = _choices(body.choices)
    graph = model.graph
    genres = model.memo.get("ask.genres", lambda: genre_vocabulary(graph))
    engine = interpreter(request)
    cache = getattr(request.app.state, "response_cache", None)
    store: Store | None = _SharedStore(cache) if cache is not None else None
    interpreted = engine.interpret(query, genres, store)
    context = core.Context(graph, model.search, _DatabaseCatalog(session), who.blocked, choices)
    result = core.answer(context, interpreted.interpretation)
    provider = engine.provider
    response.headers["Cache-Control"] = "private, no-store"
    _log(interpreted, result, started)
    return ask.AskResponse(
        interpretation=_interpretation(interpreted.interpretation, result),
        answer=ask.AskAnswer(message_id=result.message_id, params=result.params),
        entities=[_entity(e) for e in result.entities],
        results=_rows(result, model, session),
        artists=[
            convert.artist_summary(graph, a) for a in core.artist_ids(result) if a in graph.nodes
        ],
        destination=result.destination,
        model=ask.AskModelInfo(
            configured=provider is not None,
            used=interpreted.model_outcome in (ModelOutcome.USED, ModelOutcome.CACHED),
            provider=provider.name if provider else None,
            model=provider.model if provider else None,
        ),
        graph_version=model.version,
    )
