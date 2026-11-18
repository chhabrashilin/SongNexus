"""Play (US-04): the casual daily puzzle. Stateless: progress lives on the device.

The server derives each day's start and target from the date; clients only send
their moves, so the API never answers "how far is X from any artist I choose".
"""

from __future__ import annotations

import itertools
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from songnexus.core import game
from songnexus.core.graph.algorithms import bidirectional_bfs_path
from songnexus.core.graph.explain import explain_edge, explain_path
from songnexus.core.graph.model import DEFAULT_CATEGORIES, kinds_for
from songnexus.service import convert
from songnexus.service import schemas as api
from songnexus.service.deps import (
    Viewer,
    node_filter,
    parse_name,
    rate_limited,
    read_model,
    require_artist,
    viewer,
)
from songnexus.service.errors import ApiError, Status, invalid_argument
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes.common import db_session
from songnexus.storage import catalog_repository as repo

router = APIRouter(
    prefix="/v1", tags=["play"], dependencies=[Depends(rate_limited(MethodClass.ANALYZE))]
)

ModelDep = Annotated[ReadModel, Depends(read_model)]
KINDS = kinds_for(DEFAULT_CATEGORIES)
EVIDENCE_PER_STEP = 2
log = logging.getLogger(__name__)


@router.post("/puzzles:share", status_code=204, summary="ReportPuzzleShare")
def report_share() -> Response:
    """Emits one aggregate counter event, without player or puzzle identifiers.

    Count these structured events across instances in Cloud Logging. This is a
    best-effort count of successful share actions, not unique players.
    """
    log.info("game.share", extra={"metric": "game.share", "value": 1})
    return Response(status_code=204)


def _day(value: str, today: date | None = None) -> date:
    """Parses a player's local date, accepted from launch up to UTC today + 1.

    Local dates run up to 14 hours ahead of UTC (UTC+14), hence the extra day.

    Raises:
        ApiError: INVALID_ARGUMENT for a malformed date or one outside the window.
    """
    try:
        day = date.fromisoformat(value)
        if day.isoformat() != value:
            raise ValueError("non-canonical date")
    except ValueError as exc:
        raise invalid_argument("The date must be YYYY-MM-DD.", field="date") from exc
    latest = (today or datetime.now(UTC).date()) + timedelta(days=1)
    if not game.LAUNCH_DAY <= day <= latest:
        raise invalid_argument(
            "No puzzle for that date.", field="date", reason="PUZZLE_NOT_AVAILABLE"
        )
    return day


def _puzzle(model: ReadModel, day: date) -> game.Puzzle:
    graph = model.graph
    pool = [n.id for n in graph.nodes.values() if n.detail_level == "full"]
    pairs = model.memo.get(
        "puzzle_pairs", lambda: game.candidate_pairs(graph.adjacency(KINDS), pool)
    )
    try:
        return game.puzzle_for(day, pairs)
    except ValueError as exc:
        raise ApiError(
            Status.UNAVAILABLE, "No puzzle is available.", reason="PUZZLE_UNAVAILABLE"
        ) from exc


@router.get("/puzzles/{date:rid}", response_model=api.Puzzle, summary="GetDailyPuzzle")
def get_daily_puzzle(date: str, model: ModelDep, response: Response) -> api.Puzzle:
    """Returns the puzzle for a local date: the same for every player."""
    puzzle = _puzzle(model, _day(date))
    response.headers["Cache-Control"] = "public, max-age=300"
    return api.Puzzle(
        name=f"puzzles/{puzzle.day.isoformat()}",
        number=puzzle.number,
        date=puzzle.day.isoformat(),
        start=convert.artist_summary(model.graph, puzzle.start),
        target=convert.artist_summary(model.graph, puzzle.target),
        par=puzzle.par,
        graph_version=model.version,
    )


@router.post(
    "/puzzles/{date:rid}:checkMove", response_model=api.CheckMoveResponse, summary="CheckMove"
)
def check_move(
    date: str,
    body: api.CheckMoveRequest,
    model: ModelDep,
    session: Annotated[Session, Depends(db_session, scope="function")],
) -> api.CheckMoveResponse:
    """Checks one step. A wrong step reveals nothing about the puzzle (AC-4.2)."""
    puzzle = _puzzle(model, _day(date))
    graph = model.graph
    current = parse_name(body.from_artist, "artists", field="fromArtist")
    named = parse_name(body.to_artist, "artists", field="toArtist")
    require_artist(graph, current)
    require_artist(graph, named)
    adjacency = graph.adjacency(KINDS)
    if named not in adjacency[current]:
        return api.CheckMoveResponse(connected=False)
    edge = graph.edge(current, named)
    assert edge is not None
    evidence = explain_edge(graph, edge, current, KINDS, limit=EVIDENCE_PER_STEP)
    sources = repo.subject_sources(session, convert.subject_keys(evidence))
    return api.CheckMoveResponse(
        connected=True,
        artist=convert.artist_summary(graph, named),
        evidence=[convert.evidence(e, sources) for e in evidence],
        steps_to_target=game.steps_to_target(adjacency, named, puzzle.target),
        reached_target=named == puzzle.target,
    )


@router.post("/puzzles/{date:rid}:hint", response_model=api.HintResponse, summary="GetHint")
def get_hint(
    date: str,
    body: api.HintRequest,
    model: ModelDep,
    who: Annotated[Viewer, Depends(viewer)],
) -> api.HintResponse:
    """Suggests three next steps, one of them closer. Never suggests blocked artists."""
    puzzle = _puzzle(model, _day(date))
    graph = model.graph
    current = parse_name(body.from_artist, "artists", field="fromArtist")
    require_artist(graph, current)
    allowed = node_filter(who, [], include_unknown_genre=True, graph=graph).predicate(graph)
    options = game.hint(graph.adjacency(KINDS), current, puzzle.target, allowed=allowed)
    return api.HintResponse(candidates=[convert.artist_summary(graph, o) for o in options])


@router.get("/puzzles/{date:rid}:reveal", response_model=api.RevealResponse, summary="RevealPuzzle")
def reveal_puzzle(
    date: str,
    model: ModelDep,
    session: Annotated[Session, Depends(db_session, scope="function")],
) -> api.RevealResponse:
    """Returns a shortest solution with its evidence and sources."""
    puzzle = _puzzle(model, _day(date))
    graph = model.graph
    adjacency = graph.adjacency(KINDS)
    path = bidirectional_bfs_path(adjacency, puzzle.start, puzzle.target).path
    if path is None:  # Cannot happen for a fair pair; guards catalog changes mid-day.
        raise ApiError(Status.UNAVAILABLE, "No solution is available.", reason="PUZZLE_UNAVAILABLE")
    steps = explain_path(graph, path, KINDS, per_step=EVIDENCE_PER_STEP)
    sources = repo.subject_sources(session, convert.subject_keys(e for s in steps for e in s))
    return api.RevealResponse(
        steps=[
            api.PathStep(
                from_artist=convert.artist_summary(graph, u),
                to_artist=convert.artist_summary(graph, v),
                strength=round(adjacency[u][v], 4),
                evidence=[convert.evidence(e, sources) for e in explanations],
            )
            for (u, v), explanations in zip(itertools.pairwise(path), steps, strict=True)
        ],
        graph_version=model.version,
    )
