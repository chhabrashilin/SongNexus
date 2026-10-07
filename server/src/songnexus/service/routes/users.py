"""User data: account, preferences, blocked artists, profile, export and deletion.

Every method resolves ``users/{user}`` through ``authorize_user``: a viewer can
only ever reach their own data (AC-18.2), and ``users/me`` is an alias for it.
Writes check Origin and the CSRF token, use ETags against lost updates
(AIP-154), and append to the audit log.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session

from songnexus.identity.sessions import SESSION_COOKIE
from songnexus.logs import request_id_var
from songnexus.service import convert
from songnexus.service import schemas as api
from songnexus.service.deps import (
    Viewer,
    authorize_user,
    check_write_origin,
    parse_name,
    rate_limited,
    read_model,
    viewer,
)
from songnexus.service.errors import ApiError, Status, invalid_argument, not_found
from songnexus.service.pagination import paginate
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes.common import db_session
from songnexus.storage import models as m
from songnexus.storage import user_repository as users

router = APIRouter(prefix="/v1", tags=["users"])

ViewerDep = Annotated[Viewer, Depends(viewer)]
SessionDep = Annotated[Session, Depends(db_session, scope="function")]
ReadModelDep = Annotated[ReadModel, Depends(read_model)]
Write = [Depends(rate_limited(MethodClass.WRITE))]
Read = [Depends(rate_limited(MethodClass.READ))]

MAX_TOP_ARTISTS = 5
PREFERENCE_FIELDS = frozenset({"genres", "categories", "theme"})
PROFILE_FIELDS = frozenset({"topArtists", "visibility"})


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _etag(content: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    return f'W/"{digest[:16]}"'


def _timestamp(value: datetime | None) -> str | None:
    return None if value is None else value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _update_mask(mask: str | None, body_fields: set[str], allowed: frozenset[str]) -> set[str]:
    """Resolves the fields an update touches (AIP-134).

    Raises:
        ApiError: INVALID_ARGUMENT for unknown fields.
    """
    if mask is None:
        fields = body_fields & allowed
    elif mask.strip() == "*":
        fields = set(allowed)
    else:
        fields = {f.strip() for f in mask.split(",") if f.strip()}
    unknown = sorted(fields - allowed)
    if unknown:
        raise invalid_argument(f"Unknown field in updateMask: {unknown[0]}.", field="updateMask")
    return fields


def _check_etag(current: str, presented_body: str, presented_header: str | None) -> None:
    """Rejects a stale write (AC-18.3). An empty ETag means "overwrite unconditionally".

    Raises:
        ApiError: ABORTED when the presented ETag is stale.
    """
    presented = presented_header or presented_body
    if presented and presented != current:
        raise ApiError(
            Status.ABORTED,
            "The resource changed since you read it; reload and try again.",
            reason="ETAG_MISMATCH",
        )


def _audit(session: Session, user_id: str, action: str) -> None:
    users.audit(session, user_id, action, request_id_var.get(), datetime.now(UTC))


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------


@router.get("/users/{user:rid}", response_model=api.User, summary="GetUser", dependencies=Read)
def get_user(user: str, who: ViewerDep, session: SessionDep, response: Response) -> api.User:
    """Returns the signed-in user's account."""
    user_id = authorize_user(user, who)
    account = users.get_live_user(session, user_id)
    if account is None:
        raise not_found(f"users/{user_id}", reason="USER_NOT_FOUND")
    _private(response)
    return api.User(name=f"users/{user_id}", create_time=_timestamp(account.created_at) or "")


@router.delete(
    "/users/{user:rid}", response_model=api.Empty, summary="DeleteUser", dependencies=Write
)
def delete_user(
    user: str, request: Request, response: Response, who: ViewerDep, session: SessionDep
) -> api.Empty:
    """Deletes the account (AC-18.4): signed out everywhere, data gone now, purged in 30 days."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    now = datetime.now(UTC)
    _audit(session, user_id, "account.delete")
    users.erase_user(session, user_id, now)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    _private(response)
    return api.Empty()


@router.get("/users/{user:rid}:export", summary="ExportUserData", dependencies=Read)
def export_user_data(
    user: str, who: ViewerDep, session: SessionDep, response: Response
) -> dict[str, Any]:
    """Returns everything we store about the user, as JSON (target M4-07)."""
    user_id = authorize_user(user, who)
    account = users.get_live_user(session, user_id)
    if account is None:
        raise not_found(f"users/{user_id}", reason="USER_NOT_FOUND")
    prefs = session.get(m.Preferences, user_id)
    profile = session.get(m.Profile, user_id)
    audit_entries = session.query(m.AuditEntry).filter(m.AuditEntry.user_id == user_id).all()
    response.headers["Content-Disposition"] = 'attachment; filename="songnexus-data.json"'
    _private(response)
    return {
        "user": {"name": f"users/{user_id}", "createTime": _timestamp(account.created_at)},
        "preferences": None
        if prefs is None
        else {"genres": prefs.genre_ids, "categories": prefs.categories, "theme": prefs.theme},
        "blockedArtists": [f"artists/{a}" for a in users.blocked_artist_ids(session, user_id)],
        "profile": None
        if profile is None
        else {
            "topArtists": [f"artists/{a}" for a in profile.top_artist_ids],
            "visibility": profile.visibility,
        },
        "auditLog": [
            {"action": e.action, "time": _timestamp(e.created_at)}
            for e in sorted(audit_entries, key=lambda e: e.id)
        ],
    }


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


def _preferences(user_id: str, prefs: m.Preferences | None) -> api.Preferences:
    if prefs is None:
        default = api.Preferences(name=f"users/{user_id}/preferences")
        content = default.model_dump(include={"genres", "categories", "theme"}, mode="json")
        return default.model_copy(update={"etag": _etag(content)})
    return api.Preferences(
        name=f"users/{user_id}/preferences",
        genres=[f"genres/{g}" for g in prefs.genre_ids],
        categories=[api.ConnectionCategory(c) for c in prefs.categories],
        theme=api.Theme(prefs.theme),
        etag=prefs.etag,
        update_time=_timestamp(prefs.update_time),
    )


@router.get(
    "/users/{user:rid}/preferences",
    response_model=api.Preferences,
    summary="GetPreferences",
    dependencies=Read,
)
def get_preferences(
    user: str, who: ViewerDep, session: SessionDep, response: Response
) -> api.Preferences:
    """Returns the user's preferences (defaults until first saved)."""
    user_id = authorize_user(user, who)
    _private(response)
    result = _preferences(user_id, session.get(m.Preferences, user_id))
    response.headers["ETag"] = result.etag
    return result


@router.patch(
    "/users/{user:rid}/preferences",
    response_model=api.Preferences,
    summary="UpdatePreferences",
    dependencies=Write,
)
def update_preferences(
    user: str,
    body: api.Preferences,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
    update_mask: Annotated[str | None, Query(alias="updateMask")] = None,
    if_match: Annotated[str | None, Header()] = None,
) -> api.Preferences:
    """Updates preferences. Stale ETags are rejected with ABORTED (AC-18.3)."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    current = _preferences(user_id, session.get(m.Preferences, user_id))
    _check_etag(current.etag, body.etag, if_match)
    fields = _update_mask(update_mask, set(body.model_fields_set), PREFERENCE_FIELDS)

    genres = current.genres
    if "genres" in fields:
        ids = [parse_name(g, "genres", field="genres") for g in body.genres]
        missing = [g for g in ids if g not in model.graph.genre_ids]
        if missing:
            raise invalid_argument(f"Unknown genre: genres/{missing[0]}.", field="genres")
        genres = [f"genres/{g}" for g in dict.fromkeys(ids)]
    categories = (
        list(dict.fromkeys(body.categories)) if "categories" in fields else current.categories
    )
    theme = body.theme if "theme" in fields else current.theme

    content = {
        "genres": genres,
        "categories": [c.value for c in categories],
        "theme": theme.value,
    }
    now = datetime.now(UTC)
    row = session.get(m.Preferences, user_id) or m.Preferences(user_id=user_id)
    row.genre_ids = [g.removeprefix("genres/") for g in genres]
    row.categories = content["categories"]  # type: ignore[assignment]
    row.theme = theme.value
    row.etag = _etag(content)
    row.update_time = now
    session.add(row)
    _audit(session, user_id, "preferences.update")
    session.flush()
    _private(response)
    result = _preferences(user_id, row)
    response.headers["ETag"] = result.etag
    return result


# ---------------------------------------------------------------------------
# Blocked artists (US-17)
# ---------------------------------------------------------------------------


def _blocked(
    user_id: str, artist_id: str, model: ReadModel, created: datetime
) -> api.BlockedArtist:
    present = artist_id in model.graph.nodes
    return api.BlockedArtist(
        name=f"users/{user_id}/blockedArtists/{artist_id}",
        artist=convert.artist_summary(model.graph, artist_id) if present else None,
        create_time=_timestamp(created) or "",
    )


@router.get(
    "/users/{user:rid}/blockedArtists",
    response_model=api.ListBlockedArtistsResponse,
    summary="ListBlockedArtists",
    dependencies=Read,
)
def list_blocked_artists(
    user: str,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
    response: Response,
    page_size: Annotated[int, Query(alias="pageSize", ge=0, le=1000)] = 50,
    page_token: Annotated[str, Query(alias="pageToken", max_length=512)] = "",
) -> api.ListBlockedArtistsResponse:
    """Lists the user's blocked artists, oldest first."""
    user_id = authorize_user(user, who)
    rows = (
        session.query(m.BlockedArtist)
        .filter(m.BlockedArtist.user_id == user_id)
        .order_by(m.BlockedArtist.created_at, m.BlockedArtist.artist_id)
        .all()
    )
    page = paginate(
        rows, page_size=page_size, page_token=page_token, version="blocks", params=user_id
    )
    _private(response)
    return api.ListBlockedArtistsResponse(
        blocked_artists=[_blocked(user_id, r.artist_id, model, r.created_at) for r in page.items],
        next_page_token=page.next_page_token,
        total_size=page.total_size,
    )


@router.post(
    "/users/{user:rid}/blockedArtists",
    response_model=api.BlockedArtist,
    summary="CreateBlockedArtist",
    dependencies=Write,
)
def create_blocked_artist(
    user: str,
    body: api.CreateBlockedArtistRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
) -> api.BlockedArtist:
    """Blocks an artist: it disappears from lists, paths and suggestions everywhere."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    artist_id = parse_name(body.artist, "artists", field="artist")
    if artist_id not in model.graph.nodes:
        raise not_found(f"artists/{artist_id}", reason="ARTIST_NOT_FOUND")
    now = datetime.now(UTC)
    if not users.add_block(session, user_id, artist_id, now):
        raise ApiError(
            Status.ALREADY_EXISTS,
            f"artists/{artist_id} is already blocked.",
            reason="ALREADY_BLOCKED",
        )
    _audit(session, user_id, "block.create")
    _private(response)
    return _blocked(user_id, artist_id, model, now)


@router.delete(
    "/users/{user:rid}/blockedArtists/{artist:rid}",
    response_model=api.Empty,
    summary="DeleteBlockedArtist",
    dependencies=Write,
)
def delete_blocked_artist(
    user: str,
    artist: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
) -> api.Empty:
    """Unblocks an artist."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    artist_id = parse_name(artist, "artists", field="name")
    if not users.remove_block(session, user_id, artist_id):
        raise not_found(f"users/{user_id}/blockedArtists/{artist_id}", reason="BLOCK_NOT_FOUND")
    _audit(session, user_id, "block.delete")
    _private(response)
    return api.Empty()


# ---------------------------------------------------------------------------
# Profile: Top 5 (US-09, target)
# ---------------------------------------------------------------------------


def _profile(user_id: str, row: m.Profile | None) -> api.Profile:
    if row is None:
        default = api.Profile(name=f"users/{user_id}/profile")
        content = default.model_dump(include={"top_artists", "visibility"}, mode="json")
        return default.model_copy(update={"etag": _etag(content)})
    return api.Profile(
        name=f"users/{user_id}/profile",
        top_artists=[f"artists/{a}" for a in row.top_artist_ids],
        visibility=api.Visibility(row.visibility),
        etag=row.etag,
        update_time=_timestamp(row.update_time),
    )


@router.get(
    "/users/{user:rid}/profile", response_model=api.Profile, summary="GetProfile", dependencies=Read
)
def get_profile(user: str, who: ViewerDep, session: SessionDep, response: Response) -> api.Profile:
    """Returns the user's profile. Profiles are private: only the owner can read one (AC-9.2)."""
    user_id = authorize_user(user, who)
    _private(response)
    return _profile(user_id, session.get(m.Profile, user_id))


@router.patch(
    "/users/{user:rid}/profile",
    response_model=api.Profile,
    summary="UpdateProfile",
    dependencies=Write,
)
def update_profile(
    user: str,
    body: api.Profile,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
    update_mask: Annotated[str | None, Query(alias="updateMask")] = None,
    if_match: Annotated[str | None, Header()] = None,
) -> api.Profile:
    """Updates the Top 5. A sixth artist is rejected (AC-9.1)."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    current = _profile(user_id, session.get(m.Profile, user_id))
    _check_etag(current.etag, body.etag, if_match)
    fields = _update_mask(
        update_mask,
        {"topArtists" if f == "top_artists" else f for f in body.model_fields_set},
        PROFILE_FIELDS,
    )

    top = current.top_artists
    if "topArtists" in fields:
        ids = list(
            dict.fromkeys(parse_name(a, "artists", field="topArtists") for a in body.top_artists)
        )
        if len(ids) > MAX_TOP_ARTISTS:
            raise invalid_argument(f"At most {MAX_TOP_ARTISTS} top artists.", field="topArtists")
        missing = [a for a in ids if a not in model.graph.nodes]
        if missing:
            raise not_found(f"artists/{missing[0]}", reason="ARTIST_NOT_FOUND")
        top = [f"artists/{a}" for a in ids]
    visibility = body.visibility if "visibility" in fields else current.visibility

    content = {"top_artists": top, "visibility": visibility.value}
    row = session.get(m.Profile, user_id) or m.Profile(user_id=user_id)
    row.top_artist_ids = [a.removeprefix("artists/") for a in top]
    row.visibility = visibility.value
    row.etag = _etag(content)
    row.update_time = datetime.now(UTC)
    session.add(row)
    _audit(session, user_id, "profile.update")
    session.flush()
    _private(response)
    return _profile(user_id, row)
