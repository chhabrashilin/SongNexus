"""Sessions (ADR 0002): sign in with a Firebase ID token, sign out, sign out everywhere."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from songnexus.config import Settings
from songnexus.identity.sessions import SESSION_COOKIE, csrf_token_for, hash_token, new_session
from songnexus.identity.tokens import InvalidIdTokenError
from songnexus.logs import request_id_var
from songnexus.service import schemas as api
from songnexus.service.deps import (
    Viewer,
    app_state,
    check_write_origin,
    rate_limited,
    require_signed_in,
    viewer,
)
from songnexus.service.errors import ApiError, Status
from songnexus.service.ratelimit import MethodClass
from songnexus.storage import user_repository as users
from songnexus.storage.db import session_scope

router = APIRouter(prefix="/v1", tags=["identity"])

ViewerDep = Annotated[Viewer, Depends(viewer)]


def _set_cookie(response: Response, token: str, ttl: timedelta) -> None:
    # Secure, HttpOnly, host-only (no Domain) and Path=/.
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(ttl.total_seconds()),
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def local_sign_in_enabled(settings: Settings) -> bool:
    """True only in development with no Firebase project: sign-in without an identity provider.

    ``validate_for_serving`` refuses to start any other environment without a
    Firebase project, so this can never be on in a deployed service.
    """
    return settings.environment == "development" and not settings.firebase_project_id


def _start_session(
    request: Request, response: Response, who: Viewer, *, identity_uid: str, age_confirmed: bool
) -> api.SessionInfo:
    """Finds or creates the account for an identity and starts a session for it."""
    state = app_state(request)
    now = datetime.now(UTC)
    ttl = timedelta(days=state.settings.session_ttl_days)
    minted = new_session()
    with session_scope(state.engine) as session:
        user = users.find_user_by_firebase_uid(session, identity_uid)
        new_user = user is None
        if user is None:
            if not age_confirmed:
                raise ApiError(
                    Status.FAILED_PRECONDITION,
                    "Creating an account requires confirming you are 13 or older.",
                    reason="AGE_CONFIRMATION_REQUIRED",
                )
            user = users.create_user(session, identity_uid, now)
        if who.session_token is not None:
            users.delete_session(session, hash_token(who.session_token))
        users.add_session(session, minted.token_hash, user.id, now, ttl)
        users.audit(
            session,
            user.id,
            "account.create" if new_user else "session.create",
            request_id_var.get(),
            now,
        )
        user_id = user.id
    _set_cookie(response, minted.token, ttl)
    _private(response)
    return api.SessionInfo(user=f"users/{user_id}", csrf_token=minted.csrf_token, new_user=new_user)


@router.post(
    "/sessions",
    response_model=api.SessionInfo,
    summary="CreateSession",
    dependencies=[Depends(rate_limited(MethodClass.WRITE))],
)
async def create_session(
    body: api.CreateSessionRequest, request: Request, response: Response, who: ViewerDep
) -> api.SessionInfo:
    """Verifies a Firebase ID token and starts a session (sets an HttpOnly cookie).

    Creating an account requires ``ageConfirmed`` (13+). An existing session
    for this browser is replaced.
    """
    check_write_origin(request, Viewer())  # No CSRF token exists before sign-in.
    state = app_state(request)
    try:
        identity = await run_in_threadpool(state.verifier.verify, body.id_token)
    except InvalidIdTokenError as exc:
        raise ApiError(
            Status.UNAUTHENTICATED, "The sign-in token is not valid.", reason="ID_TOKEN_INVALID"
        ) from exc

    return await run_in_threadpool(
        _start_session,
        request,
        response,
        who,
        identity_uid=identity.uid,
        age_confirmed=body.age_confirmed,
    )


@router.post(
    "/sessions:local",
    response_model=api.SessionInfo,
    summary="CreateLocalSession",
    dependencies=[Depends(rate_limited(MethodClass.WRITE))],
)
def create_local_session(
    body: api.CreateLocalSessionRequest, request: Request, response: Response, who: ViewerDep
) -> api.SessionInfo:
    """Development only: signs in as a named local listener, with no identity provider.

    Exists so linked accounts and friends can be tried on a laptop without a
    Firebase project. Everywhere else it answers NOT_FOUND.
    """
    if not local_sign_in_enabled(app_state(request).settings):
        raise ApiError(Status.NOT_FOUND, "Not found.", reason="LOCAL_SIGN_IN_OFF")
    check_write_origin(request, Viewer())
    return _start_session(
        request,
        response,
        who,
        identity_uid=f"local:{body.listener}",
        age_confirmed=body.age_confirmed,
    )


@router.get("/sessions/current", response_model=api.SessionInfo, summary="GetCurrentSession")
def get_current_session(who: ViewerDep, response: Response) -> api.SessionInfo:
    """Returns the signed-in user and the CSRF token, e.g. after a page reload."""
    user_id = require_signed_in(who)
    assert who.session_token is not None
    _private(response)
    return api.SessionInfo(user=f"users/{user_id}", csrf_token=csrf_token_for(who.session_token))


@router.delete(
    "/sessions/current",
    response_model=api.Empty,
    summary="DeleteCurrentSession",
    dependencies=[Depends(rate_limited(MethodClass.WRITE))],
)
def delete_current_session(request: Request, response: Response, who: ViewerDep) -> api.Empty:
    """Signs this browser out."""
    _clear_cookie(response)
    _private(response)
    if who.session_token is None:
        return api.Empty()
    check_write_origin(request, who)
    with session_scope(app_state(request).engine) as session:
        users.delete_session(session, hash_token(who.session_token))
    return api.Empty()


@router.post(
    "/sessions:revokeAll",
    response_model=api.Empty,
    summary="RevokeAllSessions",
    dependencies=[Depends(rate_limited(MethodClass.WRITE))],
)
def revoke_all_sessions(request: Request, response: Response, who: ViewerDep) -> api.Empty:
    """Signs the user out on every device."""
    user_id = require_signed_in(who)
    check_write_origin(request, who)
    now = datetime.now(UTC)
    with session_scope(app_state(request).engine) as session:
        users.delete_user_sessions(session, user_id)
        users.audit(session, user_id, "session.revokeAll", request_id_var.get(), now)
    _clear_cookie(response)
    _private(response)
    return api.Empty()
