"""Discover: the Credit check trivia (`/v1/trivia`) and the stories feed (`/v1/stories`).

Like the daily puzzle, trivia is stateless: the server derives each day's quiz from
the date, never sends answers with the questions, and clients keep their own score.
Stories are generated once per catalog version and served as cached, paginated pages.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from songnexus.core import stories as story_core
from songnexus.core import trivia
from songnexus.core.graph.explain import Explanation
from songnexus.service import convert
from songnexus.service import schemas as api
from songnexus.service import schemas_discover as disc
from songnexus.service.deps import (
    Viewer,
    app_state,
    parse_name,
    rate_limited,
    read_model,
    viewer,
)
from songnexus.service.errors import ApiError, Status, invalid_argument
from songnexus.service.pagination import fingerprint, paginate
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes.common import PageSize, PageToken, db_session, set_cache_control
from songnexus.storage import catalog_repository as repo
from songnexus.storage import games_repository
from songnexus.storage import models as m

router = APIRouter(
    prefix="/v1", tags=["discover"], dependencies=[Depends(rate_limited(MethodClass.ANALYZE))]
)

ModelDep = Annotated[ReadModel, Depends(read_model)]
SessionDep = Annotated[Session, Depends(db_session, scope="function")]
ViewerDep = Annotated[Viewer, Depends(viewer)]

_MESSAGES = {
    trivia.QuestionKind.WHO_PRODUCED: "trivia.whoProduced",
    trivia.QuestionKind.WHO_FEATURED: "trivia.whoFeatured",
    trivia.QuestionKind.WORKED_WITH: "trivia.workedWith",
    trivia.QuestionKind.WHICH_LABEL: "trivia.whichLabel",
}
_SUBJECT_COLLECTION = {
    trivia.QuestionKind.WHO_PRODUCED: "recordings",
    trivia.QuestionKind.WHO_FEATURED: "recordings",
    trivia.QuestionKind.WHICH_LABEL: "releases",
}


def _require_flag(request: Request, flag: str) -> None:
    if not app_state(request).flags.get(flag, True):
        raise ApiError(Status.UNAVAILABLE, "This feature is switched off.", reason="FLAG_OFF")


def _trivia_enabled(request: Request) -> None:
    _require_flag(request, "play")


def _stories_enabled(request: Request) -> None:
    _require_flag(request, "stories")


def _day(value: str, today: date | None = None) -> date:
    """Parses a player's local date: from launch up to UTC today + 1 (never the future).

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
    if not trivia.LAUNCH_DAY <= day <= latest:
        raise invalid_argument(
            "No Credit check for that date.", field="date", reason="TRIVIA_NOT_AVAILABLE"
        )
    return day


def _label_facts(session: Session) -> trivia.LabelFacts:
    artists: dict[str, set[str]] = defaultdict(set)
    for release_id, artist_id in session.execute(
        select(m.ReleaseArtist.release_id, m.ReleaseArtist.artist_id)
    ):
        artists[release_id].add(artist_id)
    release_labels: dict[str, set[str]] = defaultdict(set)
    label_artists: dict[str, set[str]] = defaultdict(set)
    for release_id, label_id in session.execute(
        select(m.ReleaseLabel.release_id, m.ReleaseLabel.label_id)
    ):
        release_labels[release_id].add(label_id)
        label_artists[label_id] |= artists.get(release_id, set())
    return trivia.LabelFacts(
        {k: frozenset(v) for k, v in release_labels.items()},
        {k: frozenset(v) for k, v in artists.items()},
        {k: frozenset(v) for k, v in label_artists.items()},
    )


def _quiz(model: ReadModel, session: Session, day: date) -> trivia.Quiz:
    index = model.memo.get("trivia_index", lambda: trivia.build_index(model.graph))
    labels = model.memo.get("trivia_labels", lambda: _label_facts(session))

    def build() -> trivia.Quiz:
        try:
            return trivia.quiz_for(day, index, labels)
        except ValueError as exc:
            raise ApiError(
                Status.UNAVAILABLE, "No Credit check is available.", reason="TRIVIA_UNAVAILABLE"
            ) from exc

    return model.memo.get(f"trivia:{day.isoformat()}", build)


def _option(model: ReadModel, question: trivia.Question, option: str) -> disc.TriviaOption:
    graph = model.graph
    if question.kind is trivia.QuestionKind.WHICH_LABEL:
        return disc.TriviaOption(name=f"labels/{option}", display_name=graph.subject_titles[option])
    node = graph.nodes[option]
    return disc.TriviaOption(
        name=f"artists/{option}", display_name=node.name, disambiguation=node.disambiguation
    )


def _subject(model: ReadModel, question: trivia.Question) -> api.Subject | None:
    collection = _SUBJECT_COLLECTION.get(question.kind)
    if collection is None:
        return None
    return api.Subject(
        name=f"{collection}/{question.subject_id}", display_name=question.subject_title
    )


@router.get(
    "/trivia/{date:rid}",
    response_model=disc.TriviaQuiz,
    summary="GetTrivia",
    dependencies=[Depends(_trivia_enabled)],
)
def get_trivia(
    date: str, model: ModelDep, session: SessionDep, response: Response
) -> disc.TriviaQuiz:
    """Returns the Credit check for a local date: the same for every player, without answers."""
    quiz = _quiz(model, session, _day(date))
    response.headers["Cache-Control"] = "public, max-age=300"
    return disc.TriviaQuiz(
        name=f"trivia/{quiz.day.isoformat()}",
        number=quiz.number,
        date=quiz.day.isoformat(),
        questions=[
            disc.TriviaQuestion(
                id=q.id,
                kind=disc.TriviaQuestionKind(q.kind.name),
                message_id=_MESSAGES[q.kind],
                subject=_subject(model, q),
                artist=convert.artist_summary(model.graph, q.artist_id),
                options=[_option(model, q, o) for o in q.options],
            )
            for q in quiz.questions
        ],
        graph_version=model.version,
    )


@router.post(
    "/trivia/{date:rid}:check",
    response_model=disc.CheckTriviaResponse,
    summary="CheckTrivia",
    dependencies=[Depends(_trivia_enabled)],
)
def check_trivia(
    date: str,
    body: disc.CheckTriviaRequest,
    model: ModelDep,
    session: SessionDep,
    who: ViewerDep,
) -> disc.CheckTriviaResponse:
    """Checks one answer. The verdict comes with the right option and its credits.

    For a signed-in player the first answer to each question is kept for two days,
    so a score submitted later counts that answer (ADR 0010).
    """
    day = _day(date)
    quiz = _quiz(model, session, day)
    question = quiz.question(body.question)
    if question is None:
        raise invalid_argument("Unknown question.", field="question")
    collection = "labels" if question.kind is trivia.QuestionKind.WHICH_LABEL else "artists"
    chosen = parse_name(body.option, collection, field="option")
    if chosen not in question.options:
        raise invalid_argument("That is not one of the options.", field="option")
    if who.user_id is not None:
        games_repository.record_first_answer(
            session,
            who.user_id,
            day.isoformat(),
            question.id,
            correct=chosen == question.answer,
            now=datetime.now(UTC),
        )
    graph = model.graph
    explanations = trivia.explain_answer(graph, question)
    keys = convert.subject_keys(explanations)
    if question.kind is trivia.QuestionKind.WHICH_LABEL:
        keys = [("release", question.subject_id), ("label", question.answer)]
    sources = repo.subject_sources(session, keys)
    own_sources = (
        [s for key in keys for s in sources.get(key[1], [])]
        if question.kind is trivia.QuestionKind.WHICH_LABEL
        else []
    )
    return disc.CheckTriviaResponse(
        correct=chosen == question.answer,
        correct_option=_option(model, question, question.answer),
        evidence=[convert.evidence(e, sources) for e in explanations],
        sources=convert.source_links(own_sources),
        subject=_subject(model, question),
    )


@router.get(
    "/pathChallenges/{date:rid}",
    response_model=disc.PathChallenge,
    summary="GetPathChallenge",
    dependencies=[Depends(_trivia_enabled)],
)
def get_path_challenge(date: str, model: ModelDep, response: Response) -> disc.PathChallenge:
    """Returns the day's "connect these two" pair, 3 to 5 connections apart."""
    day = _day(date)
    index = model.memo.get("trivia_index", lambda: trivia.build_index(model.graph))
    pairs = model.memo.get("path_pairs", lambda: trivia.path_challenge_pairs(index))
    try:
        a, b, steps = trivia.path_challenge_for(day, pairs)
    except ValueError as exc:
        raise ApiError(
            Status.UNAVAILABLE, "No challenge is available.", reason="CHALLENGE_UNAVAILABLE"
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    return disc.PathChallenge(
        name=f"pathChallenges/{day.isoformat()}",
        date=day.isoformat(),
        from_artist=convert.artist_summary(model.graph, a),
        to_artist=convert.artist_summary(model.graph, b),
        steps=steps,
        graph_version=model.version,
    )


def _stories(model: ReadModel) -> tuple[story_core.Story, ...]:
    return model.memo.get("stories", lambda: story_core.generate(model.graph))


def _story(
    model: ReadModel, story: story_core.Story, sources: dict[str, list[repo.SourceRef]]
) -> disc.Story:
    graph = model.graph
    return disc.Story(
        name=f"stories/{story.id}",
        kind=disc.StoryKind(story.kind.name),
        message_id=story.message_id,
        parts=[
            disc.StoryPart(role=role, artist=convert.artist_summary(graph, artist))
            for role, artist in story.parts
        ],
        params=dict(story.params),
        credits=[convert.evidence(e, sources) for e in story.credits],
    )


@router.get(
    "/stories",
    response_model=disc.ListStoriesResponse,
    summary="ListStories",
    dependencies=[Depends(_stories_enabled)],
)
def list_stories(
    model: ModelDep,
    who: ViewerDep,
    session: SessionDep,
    response: Response,
    page_size: PageSize = 5,
    page_token: PageToken = "",
) -> disc.ListStoriesResponse:
    """Lists generated connection stories, each with the credits that prove it.

    The feed is the same for everyone for a catalog version; artists a signed-in
    viewer blocked are left out.
    """
    feed = [s for s in _stories(model) if not who.blocked.intersection(s.artist_ids)]
    page = paginate(
        feed,
        page_size=page_size,
        page_token=page_token,
        version=model.version,
        params=fingerprint("stories", sorted(who.blocked)),
    )
    explanations: list[Explanation] = [e for s in page.items for e in s.credits]
    sources = repo.subject_sources(session, convert.subject_keys(explanations))
    set_cache_control(response, who)
    return disc.ListStoriesResponse(
        stories=[_story(model, s, sources) for s in page.items],
        next_page_token=page.next_page_token,
        total_size=page.total_size,
        graph_version=model.version,
    )
