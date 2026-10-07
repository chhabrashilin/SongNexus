"""Request-scoped dependencies shared by the routes."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import Engine

from songnexus.config import Settings
from songnexus.core.graph.filters import NodeFilter
from songnexus.core.graph.model import ArtistGraph
from songnexus.identity.sessions import CSRF_HEADER, SESSION_COOKIE, csrf_matches, hash_token
from songnexus.identity.tokens import IdTokenVerifier
from songnexus.service.errors import ApiError, Status, invalid_argument, not_found
from songnexus.service.ratelimit import MethodClass, RateLimiter
from songnexus.service.readmodel import ReadModel, ReadModelHolder
from songnexus.storage import user_repository as users
from songnexus.storage.db import session_scope

# Canonical IDs are UUIDs; validating early keeps junk out of logs and queries.
_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass
class AppState:
    """Process-wide state, built once at startup and attached to the app."""

    settings: Settings
    engine: Engine
    holder: ReadModelHolder
    limiter: RateLimiter
    verifier: IdTokenVerifier
    flags: dict[str, bool] = field(default_factory=dict)


def app_state(request: Request) -> AppState:
    """Returns the process-wide state."""
    state: AppState = request.app.state.songnexus
    return state


def read_model(request: Request) -> ReadModel:
    """Returns the read model for this request (one version for the whole request)."""
    return app_state(request).holder.current()


def client_key(request: Request, trusted_proxy_hops: int) -> str:
    """Identifies the client for rate limiting.

    Behind Google's front end the client address is the entry ``trusted_proxy_hops``
    from the end of ``X-Forwarded-For``; earlier entries are client-supplied and
    untrusted. Without the header, the socket peer is used.
    """
    forwarded = [
        p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()
    ]
    if forwarded and trusted_proxy_hops > 0:
        return forwarded[-min(trusted_proxy_hops, len(forwarded))]
    return request.client.host if request.client else "unknown"


def rate_limited(method_class: MethodClass) -> Callable[[Request], None]:
    """Returns a dependency that charges one request to ``method_class``.

    Signed-in users have their own budget (keyed by user, not address), so
    people sharing a network, such as a campus behind one NAT, don't exhaust
    each other's; anonymous requests are keyed by client address.
    """

    def check(request: Request) -> None:
        state = app_state(request)
        who = viewer(request)
        key = (
            f"user:{who.user_id}"
            if who.user_id is not None
            else f"ip:{client_key(request, state.settings.trusted_proxy_hops)}"
        )
        state.limiter.check(key, method_class)

    return check


def parse_name(value: str, collection: str, *, field: str) -> str:
    """Returns the ID in a resource name (``artists/{id}``) or a bare ID.

    Raises:
        ApiError: INVALID_ARGUMENT when the value is not a valid name.
    """
    prefix = f"{collection}/"
    raw = value.removeprefix(prefix)
    if not _ID.match(raw):
        raise invalid_argument(
            f"{field} must be a resource name like `{prefix}{{id}}`.", field=field
        )
    return raw


def require_artist(graph: ArtistGraph, artist_id: str) -> None:
    """Raises NOT_FOUND unless the artist exists.

    Raises:
        ApiError: NOT_FOUND.
    """
    if artist_id not in graph.nodes:
        raise not_found(f"artists/{artist_id}", reason="ARTIST_NOT_FOUND")


@dataclass(frozen=True)
class Viewer:
    """Who is asking.

    Attributes:
        user_id: The signed-in user, or None for anonymous viewers.
        session_token: The raw session token (only to derive the CSRF token).
        blocked: Artists this viewer blocked; never shown in lists or paths.
    """

    user_id: str | None = None
    session_token: str | None = field(default=None, repr=False)
    blocked: frozenset[str] = frozenset()

    @property
    def signed_in(self) -> bool:
        """True for a signed-in user."""
        return self.user_id is not None

    @property
    def personalized(self) -> bool:
        """True when responses depend on the viewer, so they must not be shared by caches."""
        return self.signed_in


ANONYMOUS = Viewer()
_TOUCH_INTERVAL = timedelta(minutes=5)


def viewer(request: Request) -> Viewer:
    """Returns the requesting viewer, resolved from the session cookie (cached per request)."""
    cached: Viewer | None = getattr(request.state, "viewer", None)
    if cached is not None:
        return cached
    resolved = ANONYMOUS
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        now = datetime.now(UTC)
        token_hash = hash_token(token)
        with session_scope(app_state(request).engine) as session:
            found = users.find_session(session, token_hash, now)
            if found is not None:
                if now - found.last_seen_at.replace(tzinfo=UTC) > _TOUCH_INTERVAL:
                    users.touch_session(session, token_hash, now)
                blocked = frozenset(users.blocked_artist_ids(session, found.user_id))
                resolved = Viewer(found.user_id, token, blocked)
    request.state.viewer = resolved
    return resolved


def require_signed_in(who: Viewer) -> str:
    """Returns the viewer's user ID.

    Raises:
        ApiError: UNAUTHENTICATED for anonymous viewers.
    """
    if who.user_id is None:
        raise ApiError(
            Status.UNAUTHENTICATED, "Sign in to use this method.", reason="SIGN_IN_REQUIRED"
        )
    return who.user_id


def authorize_user(user: str, who: Viewer) -> str:
    """Resolves a ``users/{user}`` parameter (``me`` allowed) for the viewer.

    Raises:
        ApiError: UNAUTHENTICATED when signed out; PERMISSION_DENIED for any
            other user's resources (AC-18.2), whether or not that user exists.
    """
    viewer_id = require_signed_in(who)
    requested = user.removeprefix("users/")
    if requested not in {"me", viewer_id}:
        raise ApiError(
            Status.PERMISSION_DENIED,
            "You can only access your own data.",
            reason="NOT_YOUR_RESOURCE",
        )
    return viewer_id


def check_write_origin(request: Request, who: Viewer) -> None:
    """Rejects cross-site writes: the Origin must be allowed, and a session needs its CSRF token.

    Raises:
        ApiError: PERMISSION_DENIED.
    """
    origin = request.headers.get("origin", "")
    if origin not in app_state(request).settings.allowed_origins:
        raise ApiError(
            Status.PERMISSION_DENIED,
            "Requests that change data must come from the SongNexus app.",
            reason="ORIGIN_NOT_ALLOWED",
        )
    if who.session_token is not None and not csrf_matches(
        who.session_token, request.headers.get(CSRF_HEADER, "")
    ):
        raise ApiError(
            Status.PERMISSION_DENIED,
            f"Missing or invalid {CSRF_HEADER} header.",
            reason="CSRF_TOKEN_INVALID",
        )


def node_filter(
    viewer: Viewer, genre_ids: list[str], *, include_unknown_genre: bool, graph: ArtistGraph
) -> NodeFilter:
    """Builds the node filter for a request.

    Raises:
        ApiError: INVALID_ARGUMENT for an unknown genre.
    """
    ids = frozenset(parse_name(g, "genres", field="genres") for g in genre_ids)
    if ids:
        unknown = sorted(ids - graph.genre_ids)
        if unknown:
            raise not_found(f"genres/{unknown[0]}", reason="GENRE_NOT_FOUND")
    return NodeFilter(
        genre_ids=ids, include_unknown_genre=include_unknown_genre, blocked=viewer.blocked
    )
