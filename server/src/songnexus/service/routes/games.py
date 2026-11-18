"""Game scores and leaderboards (ADR 0010): opt-in, validated, aggregate by campus.

Submitting is the opt-in: a signed-in player sends their play (puzzle moves or
quiz answers) for today, the server computes the points against the day's
puzzle or quiz, and keeps one score per game per day. A score counts for the
player's campus (aggregate only, with a minimum number of players) and is
visible as a person's score only to accepted friends. The ``leaderboards`` flag
switches everything here off.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from songnexus.catalog.communities import load_directory
from songnexus.core import community as community_core
from songnexus.core import game as game_core
from songnexus.core import leaderboard as core
from songnexus.core import trivia
from songnexus.logs import request_id_var
from songnexus.service import community_job
from songnexus.service import schemas as api
from songnexus.service import schemas_community as community_api
from songnexus.service import schemas_games as games_api
from songnexus.service.deps import (
    Viewer,
    app_state,
    authorize_user,
    check_write_origin,
    parse_name,
    rate_limited,
    read_model,
    viewer,
)
from songnexus.service.errors import ApiError, Status, invalid_argument
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes import discover as discover_routes
from songnexus.service.routes import play as play_routes
from songnexus.service.routes.common import db_session, set_cache_control
from songnexus.service.routes.community import community_resource
from songnexus.storage import community_repository as communities
from songnexus.storage import games_repository as repo
from songnexus.storage import models as m
from songnexus.storage import social_repository as social
from songnexus.storage import user_repository as users

router = APIRouter(prefix="/v1", tags=["games"])

ViewerDep = Annotated[Viewer, Depends(viewer)]
SessionDep = Annotated[Session, Depends(db_session, scope="function")]
ModelDep = Annotated[ReadModel, Depends(read_model)]
Write = [Depends(rate_limited(MethodClass.WRITE))]
Read = [Depends(rate_limited(MethodClass.READ))]

# Scores are taken for the player's local "today": UTC today, give or take a day
# for time zones (UTC-12 to UTC+14). Archive puzzles can be played, not scored.
SCORE_WINDOW_DAYS = 1
OWN_SCORES_DAYS = 14
DateParam = Annotated[str, Query(pattern=r"^$|^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD")]


def _today() -> date:
    return datetime.now(UTC).date()


def _enabled(request: Request) -> None:
    flags = app_state(request).flags
    if not (flags.get("leaderboards", True) and flags.get("play", True)):
        raise ApiError(Status.UNAVAILABLE, "Leaderboards are switched off.", reason="FLAG_OFF")


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _time(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.isoformat().replace("+00:00", "Z")


def _score_day(value: str, launch: date) -> date:
    """Parses the play's local date and checks it is inside the score window.

    Raises:
        ApiError: INVALID_ARGUMENT (malformed); FAILED_PRECONDITION (window closed).
    """
    try:
        day = date.fromisoformat(value)
        if day.isoformat() != value:
            raise ValueError("non-canonical date")
    except ValueError as exc:
        raise invalid_argument("The date must be YYYY-MM-DD.", field="date") from exc
    today = _today()
    if day < launch or abs((day - today).days) > SCORE_WINDOW_DAYS:
        raise ApiError(
            Status.FAILED_PRECONDITION,
            "Scores are taken for today's game only.",
            reason="SCORE_WINDOW_CLOSED",
        )
    return day


def _board_day(value: str) -> date:
    if not value:
        return _today()
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise invalid_argument("The date must be YYYY-MM-DD.", field="date") from exc
    if not game_core.LAUNCH_DAY <= day <= _today() + timedelta(days=SCORE_WINDOW_DAYS):
        raise invalid_argument("No leaderboard for that date.", field="date")
    return day


def _score_resource(row: m.GameScore, synthetic: bool = False) -> games_api.GameScore:
    detail: dict[str, Any] = dict(row.detail or {})
    return games_api.GameScore(
        name=f"users/{row.user_id}/gameScores/{row.game}-{row.day}",
        game=games_api.Game(row.game),
        date=row.day,
        points=row.points,
        max_points=(
            core.PUZZLE_MAX_POINTS if row.game == core.Game.PUZZLE else core.TRIVIA_MAX_POINTS
        ),
        steps=detail.get("steps"),
        par=detail.get("par"),
        correct=detail.get("correct"),
        total=detail.get("total"),
        campus=f"communities/{row.campus_id}" if row.campus_id else None,
        submit_time=_time(row.submitted_at),
        synthetic=synthetic,
    )


def _invalid(exc: core.InvalidPlayError, field: str) -> ApiError:
    return invalid_argument(str(exc), field=field, reason=exc.reason)


def _store(
    session: Session, user_id: str, game: core.Game, day: date, score: core.Score
) -> m.GameScore:
    """Stores a validated score once; a second submission for the day is refused.

    Raises:
        ApiError: ALREADY_EXISTS (SCORE_ALREADY_SUBMITTED).
    """
    if repo.get_score(session, user_id, game.value, day.isoformat()) is not None:
        raise ApiError(
            Status.ALREADY_EXISTS,
            "You already submitted a score for this game today.",
            reason="SCORE_ALREADY_SUBMITTED",
        )
    campus = communities.memberships(session, user_id).get(community_core.Kind.CAMPUS.value)
    now = datetime.now(UTC)
    row = repo.add_score(
        session,
        user_id=user_id,
        game=game.value,
        day=day.isoformat(),
        points=score.points,
        detail=dict(score.detail),
        campus_id=campus.community_id if campus else None,
        now=now,
    )
    users.audit(
        session, user_id, f"gameScore.create.{game.value.lower()}", request_id_var.get(), now
    )
    return row


@router.post(
    "/puzzles/{date:rid}:submitScore",
    response_model=games_api.GameScore,
    summary="SubmitPuzzleScore",
    dependencies=Write,
)
def submit_puzzle_score(
    date: str,
    body: games_api.SubmitPuzzleScoreRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ModelDep,
) -> games_api.GameScore:
    """Submits today's solved puzzle (opt-in). The server checks every move and scores it.

    100 points at par, 15 fewer per extra step (at least 10). One score per day;
    it counts for your campus and your friends can see it.
    """
    _enabled(request)
    user_id = authorize_user("me", who)
    check_write_origin(request, who)
    day = _score_day(date, game_core.LAUNCH_DAY)
    puzzle = play_routes._puzzle(model, day)
    moves = [parse_name(v, "artists", field="moves") for v in body.moves]
    try:
        score = core.puzzle_score(
            moves,
            start=puzzle.start,
            target=puzzle.target,
            par=puzzle.par,
            adjacency=model.graph.adjacency(play_routes.KINDS),
        )
    except core.InvalidPlayError as exc:
        raise _invalid(exc, "moves") from exc
    row = _store(session, user_id, core.Game.PUZZLE, day, score)
    _private(response)
    return _score_resource(row)


@router.post(
    "/trivia/{date:rid}:submitScore",
    response_model=games_api.GameScore,
    summary="SubmitTriviaScore",
    dependencies=Write,
)
def submit_trivia_score(
    date: str,
    body: games_api.SubmitTriviaScoreRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ModelDep,
) -> games_api.GameScore:
    """Submits today's Credit check answers (opt-in). The server marks them.

    A question already checked with CheckTrivia counts with its first answer.
    One score per day; it counts for your campus and your friends can see it.
    """
    _enabled(request)
    user_id = authorize_user("me", who)
    check_write_origin(request, who)
    day = _score_day(date, trivia.LAUNCH_DAY)
    quiz = discover_routes._quiz(model, session, day)
    answers: dict[str, str] = {}
    for answer in body.answers:
        question = quiz.question(answer.question)
        if question is None or answer.question in answers:
            raise invalid_argument(
                "Answer every question exactly once.", field="answers", reason="TRIVIA_INCOMPLETE"
            )
        collection = "labels" if question.kind is trivia.QuestionKind.WHICH_LABEL else "artists"
        answers[answer.question] = parse_name(answer.option, collection, field="answers")
    questions = {q.id: (q.options, q.answer) for q in quiz.questions}
    try:
        score = core.trivia_score(
            answers,
            questions=questions,
            locked=repo.first_answers(session, user_id, day.isoformat()),
        )
    except core.InvalidPlayError as exc:
        raise _invalid(exc, "answers") from exc
    row = _store(session, user_id, core.Game.TRIVIA, day, score)
    _private(response)
    return _score_resource(row)


@router.get(
    "/users/{user:rid}/gameScores",
    response_model=games_api.ListGameScoresResponse,
    summary="ListGameScores",
    dependencies=Read,
)
def list_game_scores(
    user: str, request: Request, response: Response, who: ViewerDep, session: SessionDep
) -> games_api.ListGameScoresResponse:
    """Lists your own submitted scores of the last 14 days, newest first."""
    _enabled(request)
    user_id = authorize_user(user, who)
    since = (_today() - timedelta(days=OWN_SCORES_DAYS)).isoformat()
    account = users.get_live_user(session, user_id)
    synthetic = account is not None and account.synthetic_source is not None
    _private(response)
    return games_api.ListGameScoresResponse(
        game_scores=[_score_resource(r, synthetic) for r in repo.scores_of(session, user_id, since)]
    )


@router.get(
    "/leaderboards/campuses",
    response_model=games_api.CampusLeaderboard,
    summary="GetCampusLeaderboard",
    dependencies=Read,
)
def get_campus_leaderboard(
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    game: games_api.Game,
    period: games_api.LeaderboardPeriod = games_api.LeaderboardPeriod.DAY,
    date: DateParam = "",
) -> games_api.CampusLeaderboard:
    """The top 10 campuses by members' average points, and the viewer's campus rank.

    A campus appears only when at least 10 members scored in the period; players
    are shown as a range. No person is ever named here.
    """
    _enabled(request)
    first, last = core.period_days(_board_day(date), core.Period(period.value))
    rows = repo.period_scores(
        session,
        game.value,
        first.isoformat(),
        last.isoformat(),
        include_synthetic=community_job.include_synthetic(app_state(request).settings),
    )
    standings, below = core.campus_standings(core.PlayerScore(*r) for r in rows)
    directory = load_directory()
    shown = [s for s in standings if s.campus in directory.by_id]

    def players(count: int) -> community_api.ListenerRange:
        found = community_core.band(count)
        if found is None:  # never happens past the floor; fail closed rather than leak
            raise ApiError(Status.INTERNAL, "Leaderboard floor violated.", reason="BOARD_FLOOR")
        return community_api.ListenerRange(min=found.low, max=found.high)

    viewer_campus = None
    if who.user_id is not None:
        membership = communities.memberships(session, who.user_id).get("CAMPUS")
        campus = directory.by_id.get(membership.community_id) if membership else None
        if campus is None:
            viewer_campus = games_api.ViewerCampus(state=games_api.ViewerCampusState.NO_CAMPUS)
        else:
            ranked = next((s for s in shown if s.campus == campus.id), None)
            viewer_campus = games_api.ViewerCampus(
                state=(
                    games_api.ViewerCampusState.RANKED
                    if ranked
                    else games_api.ViewerCampusState.NEEDS_PLAYERS
                ),
                community=community_resource(campus),
                rank=ranked.rank if ranked else None,
                players_needed=0 if ranked else core.MIN_CAMPUS_PLAYERS - below.get(campus.id, 0),
            )
    top = shown[: core.MAX_CAMPUSES]
    set_cache_control(response, who)
    return games_api.CampusLeaderboard(
        name="leaderboards/campuses",
        game=game,
        period=period,
        start_date=first.isoformat(),
        end_date=last.isoformat(),
        min_players=core.MIN_CAMPUS_PLAYERS,
        campuses=[
            games_api.CampusStanding(
                rank=s.rank,
                community=community_resource(directory.by_id[s.campus]),
                players=players(s.players),
                average_points=round(s.average),
            )
            for s in top
        ],
        ranked_campuses=len(shown),
        viewer_campus=viewer_campus,
        demo_data=any(s.demo for s in top),
    )


@router.get(
    "/users/{user:rid}/friendLeaderboard",
    response_model=games_api.FriendLeaderboard,
    summary="GetFriendLeaderboard",
    dependencies=Read,
)
def get_friend_leaderboard(
    user: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    game: games_api.Game,
    period: games_api.LeaderboardPeriod = games_api.LeaderboardPeriod.WEEK,
    date: DateParam = "",
) -> games_api.FriendLeaderboard:
    """You and your accepted friends who submitted scores in the period, best first."""
    _enabled(request)
    user_id = authorize_user(user, who)
    first, last = core.period_days(_board_day(date), core.Period(period.value))
    hidden = social.blocked_either_way(session, user_id)
    people = [
        user_id,
        *(f.friend_id for f in social.friends(session, user_id) if f.friend_id not in hidden),
    ]
    standings = core.friend_standings(
        repo.friend_scores(session, people, game.value, first.isoformat(), last.isoformat())
    )
    names = social.display_names(session, [s.user_id for s in standings])
    _private(response)
    return games_api.FriendLeaderboard(
        name=f"users/{user_id}/friendLeaderboard",
        game=game,
        period=period,
        start_date=first.isoformat(),
        end_date=last.isoformat(),
        standings=[
            games_api.FriendStanding(
                rank=s.rank,
                person=api.Person(user=f"users/{s.user_id}", display_name=names.get(s.user_id, "")),
                points=s.points,
                days_played=s.days_played,
                is_viewer=s.user_id == user_id,
            )
            for s in standings
        ],
    )
