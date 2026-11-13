"""Linked listening accounts (R2-6, ADR 0006): offer, link, sync, unlink, and the listening view.

Writes check Origin and the CSRF token like every user write. The OAuth callback
is a top-level GET from the provider; it is protected instead by the flow's state,
which is single use, short-lived and bound to the session that started it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from songnexus.accounts.connectors import Provider
from songnexus.accounts.crypto import TokenCipher
from songnexus.core.resolution import Decision
from songnexus.logs import request_id_var
from songnexus.service import convert, linking
from songnexus.service import schemas as api
from songnexus.service.deps import (
    Viewer,
    app_state,
    authorize_user,
    check_write_origin,
    rate_limited,
    read_model,
    viewer,
)
from songnexus.service.errors import ApiError, Status, invalid_argument, not_found
from songnexus.service.pagination import paginate
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes.common import PageSize, PageToken, db_session
from songnexus.storage import accounts_repository as repo
from songnexus.storage import models as m
from songnexus.storage import user_repository as users

router = APIRouter(prefix="/v1", tags=["accounts"])

# "Sync now" calls the provider: at most once a minute per account.
MIN_SYNC_NOW_INTERVAL = timedelta(seconds=60)

ViewerDep = Annotated[Viewer, Depends(viewer)]
SessionDep = Annotated[Session, Depends(db_session, scope="function")]
ReadModelDep = Annotated[ReadModel, Depends(read_model)]
Write = [Depends(rate_limited(MethodClass.WRITE))]
Read = [Depends(rate_limited(MethodClass.READ))]


def _time(value: datetime | None) -> str | None:
    return None if value is None else value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _account(row: m.LinkedAccount) -> api.LinkedAccount:
    return api.LinkedAccount(
        name=f"users/{row.user_id}/linkedAccounts/{row.provider}",
        provider=api.ListeningProvider(row.provider),
        external_user=row.external_user,
        status=api.LinkedAccountStatus(row.status),
        link_time=_time(row.linked_at) or "",
        last_sync_time=_time(row.last_sync_at),
        next_sync_time=_time(row.next_sync_after) if row.status == linking.ACTIVE else None,
        unmatched_plays=row.unmatched_plays,
    )


def _registry(request: Request) -> dict[Provider, linking.ProviderInfo]:
    state = app_state(request)
    if not state.flags.get("linkedAccounts", True):
        raise ApiError(Status.UNAVAILABLE, "Linked accounts are switched off.", reason="FLAG_OFF")
    return linking.registry(state.settings, state.cipher)


def _offered(request: Request, provider: api.ListeningProvider) -> linking.ProviderInfo:
    info = _registry(request)[Provider(provider.value)]
    if not info.available:
        raise ApiError(
            Status.FAILED_PRECONDITION,
            f"{provider} is not offered here.",
            reason=info.unavailable_reason or "PROVIDER_UNAVAILABLE",
        )
    return info


def _cipher(request: Request) -> TokenCipher:
    cipher = app_state(request).cipher
    if cipher is None:
        raise ApiError(
            Status.FAILED_PRECONDITION, "Token keys are not configured.", reason="NO_TOKEN_KEYS"
        )
    return cipher


def _link_error(exc: linking.LinkError) -> ApiError:
    return ApiError(Status.FAILED_PRECONDITION, str(exc), reason=exc.reason)


def resolver(model: ReadModel) -> Callable[[Sequence[str]], list[str | None]]:
    """Name resolution with the import matcher: only confident matches count."""

    def resolve(names: Sequence[str]) -> list[str | None]:
        return [
            r.entity_id if r.decision is Decision.MATCHED else None
            for r in model.resolutions.resolve(model.search, list(names))
        ]

    return resolve


@router.get(
    "/users/{user:rid}/linkedAccounts",
    response_model=api.ListLinkedAccountsResponse,
    summary="ListLinkedAccounts",
    dependencies=Read,
)
def list_linked_accounts(
    user: str, request: Request, response: Response, who: ViewerDep, session: SessionDep
) -> api.ListLinkedAccountsResponse:
    """Lists every provider: how it links, whether it is offered here, and the link if any."""
    user_id = authorize_user(user, who)
    linked = {row.provider: row for row in repo.list_accounts(session, user_id)}
    _private(response)
    return api.ListLinkedAccountsResponse(
        providers=[
            api.ProviderOffer(
                provider=api.ListeningProvider(info.provider.value),
                method=api.LinkMethod(info.method.value),
                available=info.available,
                unavailable_reason=info.unavailable_reason,
                linked_account=_account(linked[info.provider.value])
                if info.provider.value in linked
                else None,
            )
            for info in _registry(request).values()
        ],
        sync_interval_minutes=app_state(request).settings.sync_interval_minutes,
    )


@router.post(
    "/users/{user:rid}/linkedAccounts:start",
    response_model=api.StartLinkResponse,
    summary="StartLink",
    dependencies=Write,
)
def start_link(
    user: str,
    body: api.StartLinkRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
) -> api.StartLinkResponse:
    """Starts linking a provider that approves on its own site; returns where to go."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    info = _offered(request, body.provider)
    if info.method is not linking.Method.REDIRECT or who.session_token is None:
        raise invalid_argument(
            f"{body.provider} does not link through a redirect.", field="provider"
        )
    url = linking.start(
        session,
        app_state(request).settings,
        _cipher(request),
        info,
        user_id=user_id,
        session_token=who.session_token,
        now=datetime.now(UTC),
    )
    _private(response)
    return api.StartLinkResponse(authorization_url=url)


@router.get(
    "/oauth/{provider:rid}/callback",
    summary="FinishLink",
    include_in_schema=True,
    response_class=RedirectResponse,
    status_code=303,
    dependencies=Write,
)
def finish_link(
    provider: str,
    request: Request,
    who: ViewerDep,
    session: SessionDep,
    state: Annotated[str, Query(max_length=128)] = "",
    code: Annotated[str, Query(max_length=2048)] = "",
    token: Annotated[str, Query(max_length=2048, description="Last.fm and Libre.fm.")] = "",
    error: Annotated[str, Query(max_length=128)] = "",
) -> RedirectResponse:
    """The provider sends the listener back here; then on to the You page with the outcome."""
    settings = app_state(request).settings
    target = f"{settings.app_origin.rstrip('/')}/you"
    try:
        name = api.ListeningProvider(provider.upper())
    except ValueError:
        return RedirectResponse(f"{target}?linkError=PROVIDER_UNKNOWN", status_code=303)
    if error or not state or not (code or token):
        return RedirectResponse(f"{target}?linkError=LINK_DECLINED", status_code=303)
    try:
        info = _offered(request, name)
        with app_state(request).outbound_http() as http:
            row = linking.finish(
                session,
                http,
                settings,
                _cipher(request),
                info,
                state=state,
                code=code or token,
                session_token=who.session_token,
                now=datetime.now(UTC),
            )
    except linking.LinkError as exc:
        return RedirectResponse(f"{target}?linkError={exc.reason}", status_code=303)
    except ApiError as exc:
        return RedirectResponse(f"{target}?linkError={exc.reason}", status_code=303)
    users.audit(session, row.user_id, "link.create", request_id_var.get(), datetime.now(UTC))
    return RedirectResponse(f"{target}?linked={name.value}", status_code=303)


@router.post(
    "/users/{user:rid}/linkedAccounts",
    response_model=api.LinkedAccount,
    summary="CreateLinkedAccount",
    dependencies=Write,
)
def create_linked_account(
    user: str,
    body: api.CreateLinkedAccountRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
) -> api.LinkedAccount:
    """Links ListenBrainz (user token) or Apple Music (MusicKit user token)."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    info = _offered(request, body.provider)
    if info.method not in {linking.Method.TOKEN, linking.Method.MUSICKIT}:
        raise invalid_argument(f"{body.provider} links through its own site.", field="provider")
    try:
        with app_state(request).outbound_http() as http:
            row = linking.link_with_token(
                session,
                http,
                _cipher(request),
                info,
                user_id=user_id,
                token=body.token,
                now=datetime.now(UTC),
            )
    except linking.LinkError as exc:
        raise _link_error(exc) from exc
    users.audit(session, user_id, "link.create", request_id_var.get(), datetime.now(UTC))
    _private(response)
    return _account(row)


@router.post(
    "/users/{user:rid}/linkedAccounts/{provider:rid}:sync",
    response_model=api.SyncLinkedAccountResponse,
    summary="SyncLinkedAccount",
    dependencies=Write,
)
def sync_linked_account(
    user: str,
    provider: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
) -> api.SyncLinkedAccountResponse:
    """Syncs one linked account now ("Sync now")."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    name = _provider(provider)
    row = repo.get_account(session, user_id, name.value)
    if row is None:
        raise not_found(f"users/{user_id}/linkedAccounts/{name.value}", reason="LINK_NOT_FOUND")
    info = _offered(request, name)
    now = datetime.now(UTC)
    last = row.last_sync_at
    if last is not None and now - last.replace(tzinfo=UTC) < MIN_SYNC_NOW_INTERVAL:
        raise ApiError(
            Status.RESOURCE_EXHAUSTED,
            "This account was synced a moment ago.",
            reason="SYNC_TOO_SOON",
        )
    with app_state(request).outbound_http() as http:
        outcome = linking.sync_account(
            session,
            http,
            app_state(request).settings,
            _cipher(request),
            info=info,
            account=row,
            known_artists=lambda a: a in model.graph.nodes,
            resolve_names=resolver(model),
            now=now,
        )
    _private(response)
    return api.SyncLinkedAccountResponse(
        linked_account=_account(row),
        synced=outcome.error is None,
        plays=outcome.plays,
        artists=outcome.artists,
        unmatched_plays=outcome.unmatched,
    )


def _provider(value: str) -> api.ListeningProvider:
    try:
        return api.ListeningProvider(value.upper())
    except ValueError as exc:
        raise invalid_argument(f"Unknown provider {value!r}.", field="provider") from exc


@router.delete(
    "/users/{user:rid}/linkedAccounts/{provider:rid}",
    response_model=api.Empty,
    summary="DeleteLinkedAccount",
    dependencies=Write,
)
def delete_linked_account(
    user: str,
    provider: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
) -> api.Empty:
    """Unlinks: deletes the token and every play count synced from the account."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    name = _provider(provider)
    if not repo.unlink(session, user_id, name.value):
        raise not_found(f"users/{user_id}/linkedAccounts/{name.value}", reason="LINK_NOT_FOUND")
    users.audit(session, user_id, "link.delete", request_id_var.get(), datetime.now(UTC))
    _private(response)
    return api.Empty()


@router.get(
    "/users/{user:rid}/listening",
    response_model=api.ListListeningResponse,
    summary="ListListening",
    dependencies=Read,
)
def list_listening(
    user: str,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
    page_size: PageSize = 50,
    page_token: PageToken = "",
) -> api.ListListeningResponse:
    """The listener's artists from linked accounts, most played first (blocked artists hidden)."""
    user_id = authorize_user(user, who)
    graph = model.graph
    combined: dict[str, tuple[int, datetime | None, set[str]]] = {}
    for tally in repo.listening(session, user_id):
        if tally.artist_id not in graph.nodes or tally.artist_id in who.blocked:
            continue
        plays, last, providers = combined.get(tally.artist_id, (0, None, set()))
        latest = max((t for t in (last, tally.last_played_at) if t is not None), default=None)
        combined[tally.artist_id] = (plays + tally.plays, latest, providers | {tally.provider})
    ordered = sorted(combined, key=lambda a: (-combined[a][0], graph.nodes[a].name, a))
    page = paginate(
        ordered,
        page_size=page_size,
        page_token=page_token,
        version=model.version,
        params=f"listening:{user_id}",
    )
    _private(response)
    return api.ListListeningResponse(
        artists=[
            api.ListeningArtist(
                artist=convert.artist_summary(graph, a),
                plays=combined[a][0],
                last_play_time=_time(combined[a][1]),
                providers=sorted(api.ListeningProvider(p) for p in combined[a][2]),
            )
            for a in page.items
        ],
        next_page_token=page.next_page_token,
        total_size=page.total_size,
    )
