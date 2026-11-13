"""Linking flows: how each service proves the listener owns the account (ADR 0006).

* **Spotify**: OAuth 2 authorization code with PKCE (S256); refresh tokens.
* **YouTube Music**: Google OAuth 2 authorization code with PKCE and the read-only
  YouTube scope; refresh tokens (``access_type=offline``).
* **Deezer**: OAuth authorization code; ``offline_access`` tokens do not expire.
* **Last.fm / Libre.fm**: web authentication; the callback token is exchanged for
  a session key with a signed ``auth.getSession`` call, which also names the user.
* **ListenBrainz**: the listener pastes their user token; ``validate-token``
  confirms it and names the user.
* **Apple Music**: MusicKit JS in the browser returns a Music-User-Token; the
  server stores it with the configured developer token.

State and PKCE verifiers are generated here and stored server-side by the
caller, bound to the session (``identity``), single use, ten-minute lifetime.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from songnexus.accounts.connectors import (
    HTTP_OK,
    ConnectorError,
    Provider,
    RevokedError,
)

STATE_TTL_S = 600


@dataclass(frozen=True)
class ProviderConfig:
    """Keys and endpoints for one service; a provider without keys is not offered."""

    client_id: str = ""
    client_secret: str = ""
    api_url: str = ""

    @property
    def configured(self) -> bool:
        """True when the keys the provider needs are present."""
        return bool(self.client_id)


@dataclass(frozen=True)
class Linked:
    """The result of a completed link."""

    external_user: str
    access_token: str
    refresh_token: str = ""
    expires_at: int | None = None  # Unix seconds; None when the token does not expire


def new_state() -> str:
    """A random, URL-safe state value (also the key of the stored flow)."""
    return secrets.token_urlsafe(32)


def pkce_pair() -> tuple[str, str]:
    """Returns (verifier, S256 challenge) for PKCE."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


SPOTIFY_SCOPES = "user-read-recently-played"  # only what sync reads
YOUTUBE_SCOPES = "https://www.googleapis.com/auth/youtube.readonly"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - an endpoint, not a secret
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"  # noqa: S105 - an endpoint


def authorization_url(
    provider: Provider, config: ProviderConfig, *, redirect_uri: str, state: str, challenge: str
) -> str:
    """Returns where to send the listener to approve the link.

    Raises:
        ValueError: The provider does not link through a browser redirect.
    """
    if provider is Provider.SPOTIFY:
        return "https://accounts.spotify.com/authorize?" + urlencode(
            {
                "client_id": config.client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": SPOTIFY_SCOPES,
                "state": state,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
            }
        )
    if provider is Provider.YOUTUBE_MUSIC:
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": config.client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": YOUTUBE_SCOPES,
                "state": state,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
                "access_type": "offline",  # a refresh token, so sync works while away
                "prompt": "consent",  # Google returns a refresh token only on consent
                "include_granted_scopes": "false",
            }
        )
    if provider is Provider.DEEZER:
        return "https://connect.deezer.com/oauth/auth.php?" + urlencode(
            {
                "app_id": config.client_id,
                "redirect_uri": redirect_uri,
                "perms": "listening_history,offline_access",
                "state": state,
            }
        )
    if provider in {Provider.LASTFM, Provider.LIBREFM}:
        host = "https://www.last.fm" if provider is Provider.LASTFM else "https://libre.fm"
        callback = f"{redirect_uri}{'&' if '?' in redirect_uri else '?'}state={state}"
        return f"{host}/api/auth/?" + urlencode({"api_key": config.client_id, "cb": callback})
    raise ValueError(f"{provider} does not link through a redirect")


def _post(http: httpx.Client, url: str, **kwargs: Any) -> Any:
    try:
        response = http.post(url, **kwargs)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"POST {httpx.URL(url).host}: {type(exc).__name__}") from exc
    if response.status_code != HTTP_OK:
        raise RevokedError(f"{httpx.URL(url).host} refused the link ({response.status_code})")
    return response.json()


def _get(http: httpx.Client, url: str, **kwargs: Any) -> Any:
    try:
        response = http.get(url, **kwargs)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"GET {httpx.URL(url).host}: {type(exc).__name__}") from exc
    if response.status_code != HTTP_OK:
        raise RevokedError(f"{httpx.URL(url).host} refused the link ({response.status_code})")
    return response.json()


def lastfm_signature(params: dict[str, str], secret: str) -> str:
    """The ``api_sig`` Last.fm requires: md5 of sorted key-value pairs plus the secret."""
    raw = "".join(f"{k}{v}" for k, v in sorted(params.items()) if k not in {"format", "callback"})
    return hashlib.md5((raw + secret).encode(), usedforsecurity=False).hexdigest()


def complete(
    http: httpx.Client,
    provider: Provider,
    config: ProviderConfig,
    *,
    code: str,
    redirect_uri: str,
    verifier: str = "",
) -> Linked:
    """Exchanges the callback code (or Last.fm token) for credentials.

    Raises:
        RevokedError: The service refused the exchange.
        ConnectorError: The service could not be reached.
    """
    if provider is Provider.SPOTIFY:
        token = _post(
            http,
            SPOTIFY_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": config.client_id,
                "code_verifier": verifier,
            },
        )
        me = _get(
            http,
            "https://api.spotify.com/v1/me",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        return Linked(
            external_user=str(me.get("id", "")),
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token", ""),
            expires_at=int(time.time()) + int(token.get("expires_in", 3600)),
        )
    if provider is Provider.YOUTUBE_MUSIC:
        token = _post(
            http,
            GOOGLE_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code_verifier": verifier,
            },
        )
        channels = _get(
            http,
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        items = channels.get("items") or [{}]
        return Linked(
            external_user=str((items[0].get("snippet") or {}).get("title") or "YouTube"),
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token", ""),
            expires_at=int(time.time()) + int(token.get("expires_in", 3600)),
        )
    if provider is Provider.DEEZER:
        token = _get(
            http,
            "https://connect.deezer.com/oauth/access_token.php",
            params={
                "app_id": config.client_id,
                "secret": config.client_secret,
                "code": code,
                "output": "json",
            },
        )
        me = _get(
            http, "https://api.deezer.com/user/me", params={"access_token": token["access_token"]}
        )
        return Linked(external_user=str(me.get("id", "")), access_token=token["access_token"])
    if provider in {Provider.LASTFM, Provider.LIBREFM}:
        params = {"method": "auth.getSession", "api_key": config.client_id, "token": code}
        signed = {
            **params,
            "api_sig": lastfm_signature(params, config.client_secret),
            "format": "json",
        }
        body = _get(http, config.api_url, params=signed)
        session = body.get("session") or {}
        if not session.get("key"):
            raise RevokedError(f"{provider} refused the link")
        return Linked(external_user=str(session.get("name", "")), access_token=session["key"])
    raise ValueError(f"{provider} does not complete through a callback")


REFRESHABLE = frozenset({Provider.SPOTIFY, Provider.YOUTUBE_MUSIC})


def refresh(
    http: httpx.Client, provider: Provider, config: ProviderConfig, refresh_token: str
) -> Linked:
    """Returns fresh credentials for Spotify or YouTube (a refresh token may rotate).

    Raises:
        RevokedError: The listener revoked access.
        ValueError: The provider's tokens do not refresh.
    """
    if provider not in REFRESHABLE:
        raise ValueError(f"{provider} tokens do not refresh")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": config.client_id,
    }
    if provider is Provider.YOUTUBE_MUSIC:
        data["client_secret"] = config.client_secret
    url = GOOGLE_TOKEN_URL if provider is Provider.YOUTUBE_MUSIC else SPOTIFY_TOKEN_URL
    token = _post(http, url, data=data)
    return Linked(
        external_user="",
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token", refresh_token),
        expires_at=int(time.time()) + int(token.get("expires_in", 3600)),
    )


def validate_listenbrainz_token(http: httpx.Client, api_url: str, token: str) -> Linked:
    """Confirms a ListenBrainz user token and returns the user it belongs to.

    Raises:
        RevokedError: The token is not valid.
    """
    body = _get(
        http, f"{api_url.rstrip('/')}/1/validate-token", headers={"Authorization": f"Token {token}"}
    )
    if not body.get("valid") or not body.get("user_name"):
        raise RevokedError("ListenBrainz did not accept the token")
    return Linked(external_user=str(body["user_name"]), access_token=token)
