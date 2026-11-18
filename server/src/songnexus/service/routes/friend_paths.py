"""Friend paths: how your top artists connect to an accepted friend's (growth loop 4).

Both people must have turned on ``shareTopArtists`` in their social profile
(off by default), be friends, and not have blocked each other; anything else
looks like "no such friend" except a sharing refusal, which says whose sharing
is off. Artists the viewer blocked never appear (US-17), and artists the
friend blocked are left out of the friend's list. Under the ``friends`` flag.
"""

from __future__ import annotations

import itertools
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from songnexus.core import friend_paths as core
from songnexus.core.graph.explain import explain_path
from songnexus.core.graph.model import DEFAULT_CATEGORIES, kinds_for
from songnexus.service import convert
from songnexus.service import schemas as api
from songnexus.service import schemas_games as games_api
from songnexus.service.deps import (
    Viewer,
    app_state,
    authorize_user,
    node_filter,
    parse_name,
    rate_limited,
    read_model,
    viewer,
)
from songnexus.service.errors import ApiError, Status, not_found
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes.common import db_session
from songnexus.storage import accounts_repository as accounts
from songnexus.storage import catalog_repository as catalog
from songnexus.storage import models as m
from songnexus.storage import social_repository as social
from songnexus.storage import user_repository as users

router = APIRouter(
    prefix="/v1", tags=["social"], dependencies=[Depends(rate_limited(MethodClass.ANALYZE))]
)

ViewerDep = Annotated[Viewer, Depends(viewer)]
SessionDep = Annotated[Session, Depends(db_session, scope="function")]
ModelDep = Annotated[ReadModel, Depends(read_model)]
KINDS = kinds_for(DEFAULT_CATEGORIES)
EVIDENCE_PER_STEP = 1


def _top_artists(
    session: Session, model: ReadModel, user_id: str, hidden: frozenset[str]
) -> list[str]:
    profile = session.get(m.Profile, user_id)
    return core.top_artists(
        list(profile.top_artist_ids) if profile is not None else [],
        ((t.artist_id, t.plays) for t in accounts.listening(session, user_id)),
        known=lambda a: a in model.graph.nodes,
        hidden=hidden,
    )


def _not_sharing(reason: str, message: str) -> ApiError:
    return ApiError(Status.FAILED_PRECONDITION, message, reason=reason)


@router.get(
    "/users/{user:rid}/friends/{friend:rid}/paths",
    response_model=games_api.FriendPaths,
    summary="GetFriendPaths",
)
def get_friend_paths(
    user: str,
    friend: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ModelDep,
) -> games_api.FriendPaths:
    """Shared artists, shared collaborators and the shortest paths between your top artists.

    Top artists are your chosen Top 5, then your most played linked-account artists.

    Errors: FRIEND_NOT_FOUND (not friends, or blocked either way), VIEWER_NOT_SHARING
    and FRIEND_NOT_SHARING (``shareTopArtists`` off), NO_TOP_ARTISTS (metadata
    ``side``: ``viewer`` or ``friend``).
    """
    if not app_state(request).flags.get("friends", True):
        raise ApiError(Status.UNAVAILABLE, "Friends are switched off.", reason="FLAG_OFF")
    user_id = authorize_user(user, who)
    friend_id = parse_name(friend, "users", field="friend")
    if (
        friend_id == user_id
        or not social.are_friends(session, user_id, friend_id)
        or social.is_blocked_either_way(session, user_id, friend_id)
    ):
        raise not_found(f"users/{user_id}/friends/{friend_id}", reason="FRIEND_NOT_FOUND")
    if not social.shares_top_artists(session, user_id):
        raise _not_sharing(
            "VIEWER_NOT_SHARING", "Turn on sharing your top artists with friends first."
        )
    if not social.shares_top_artists(session, friend_id):
        raise _not_sharing("FRIEND_NOT_SHARING", "Your friend doesn't share their top artists.")

    graph = model.graph
    friend_blocked = frozenset(users.blocked_artist_ids(session, friend_id))
    mine = _top_artists(session, model, user_id, who.blocked)
    theirs = _top_artists(session, model, friend_id, who.blocked | friend_blocked)
    for side, artists in (("viewer", mine), ("friend", theirs)):
        if not artists:
            raise ApiError(
                Status.FAILED_PRECONDITION,
                "No top artists yet: pick a Top 5 or link a listening service.",
                reason="NO_TOP_ARTISTS",
                metadata={"side": side},
            )

    allowed = node_filter(who, [], include_unknown_genre=True, graph=graph).predicate(graph)
    adjacency = graph.adjacency(KINDS)
    found = core.connect(adjacency, mine, theirs, allowed=allowed)
    explained = [explain_path(graph, p, KINDS, per_step=EVIDENCE_PER_STEP) for p in found.paths]
    sources = catalog.subject_sources(
        session, convert.subject_keys(e for steps in explained for step in steps for e in step)
    )
    names = social.display_names(session, [friend_id])
    friend_account = users.get_live_user(session, friend_id)

    def summary(artist_id: str) -> api.ArtistSummary:
        return convert.artist_summary(graph, artist_id)

    response.headers["Cache-Control"] = "private, no-store"
    return games_api.FriendPaths(
        name=f"users/{user_id}/friends/{friend_id}/paths",
        friend=api.Person(user=f"users/{friend_id}", display_name=names.get(friend_id, "")),
        viewer_artists=[summary(a) for a in mine],
        friend_artists=[summary(a) for a in theirs],
        shared_artists=[summary(a) for a in found.shared],
        shared_collaborators=[
            games_api.SharedCollaborator(
                artist=summary(c.artist_id),
                viewer_artists=[f"artists/{a}" for a in c.mine],
                friend_artists=[f"artists/{a}" for a in c.theirs],
            )
            for c in found.collaborators
        ],
        paths=[
            games_api.FriendPath(
                from_artist=summary(path[0]),
                to_artist=summary(path[-1]),
                steps=[
                    api.PathStep(
                        from_artist=summary(u),
                        to_artist=summary(v),
                        strength=round(adjacency[u][v], 4),
                        evidence=[convert.evidence(e, sources) for e in explanations],
                    )
                    for (u, v), explanations in zip(itertools.pairwise(path), steps, strict=True)
                ],
            )
            for path, steps in zip(found.paths, explained, strict=True)
        ],
        demo_data=friend_account is not None and friend_account.synthetic_source is not None,
        graph_version=model.version,
    )
