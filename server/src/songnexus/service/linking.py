"""Linked accounts end to end (ADR 0006): which providers are offered, linking, sync, unlinking.

Routes call these functions; they hold no HTTP request state of their own, so
the scheduled job (``songnexus sync-accounts``) and "Sync now" share one path.
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from songnexus.accounts import connectors as c
from songnexus.accounts.crypto import TokenCipher, TokenCipherError, new_key
from songnexus.accounts.oauth import (
    REFRESHABLE,
    STATE_TTL_S,
    Linked,
    ProviderConfig,
    authorization_url,
    complete,
    new_state,
    pkce_pair,
    refresh,
    validate_listenbrainz_token,
)
from songnexus.accounts.sync import Tally, aggregate, merge
from songnexus.config import Settings
from songnexus.storage import accounts_repository as repo
from songnexus.storage import models as m

log = logging.getLogger(__name__)

MAX_PAGES_PER_SYNC = 5
MAX_BACKOFF = timedelta(hours=24)
EXPIRY_MARGIN = timedelta(seconds=60)
ACTIVE, NEEDS_RELINK = "ACTIVE", "NEEDS_RELINK"


class Method(enum.StrEnum):
    """How a listener links a provider."""

    REDIRECT = "REDIRECT"  # approve on the provider's site (OAuth, Last.fm web auth)
    TOKEN = "TOKEN"  # noqa: S105 - a method name, not a secret: paste a ListenBrainz token
    MUSICKIT = "MUSICKIT"  # authorize in the browser with MusicKit JS (Apple Music)
    FILE = "FILE"  # no history API: import an export file on the device


@dataclass(frozen=True)
class ProviderInfo:
    """A provider as offered to listeners."""

    provider: c.Provider
    method: Method
    config: ProviderConfig
    connector: c.Connector | None
    available: bool
    unavailable_reason: str = ""


class LinkError(RuntimeError):
    """A link could not be made; ``reason`` is the API error reason."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


_LOCAL_KEY_ID = "local"


def cipher_from(settings: Settings) -> TokenCipher | None:
    """Returns the token cipher, or None when no keys are configured (then nothing is offered).

    In development without configured keys, a key is generated once and kept in a
    git-ignored file, so linking works with zero setup. Every other environment
    must configure ``SONGNEXUS_TOKEN_KEYS`` (from Secret Manager).
    """
    if settings.token_keys:
        current = settings.token_key_id or sorted(settings.token_keys)[-1]
        return TokenCipher.from_config(settings.token_keys, current)
    if settings.environment != "development":
        return None
    path = settings.local_token_key_path
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({_LOCAL_KEY_ID: new_key()}), encoding="utf-8")
        keys = json.loads(path.read_text(encoding="utf-8"))
        return TokenCipher.from_config(keys, _LOCAL_KEY_ID)
    except (OSError, ValueError, TokenCipherError):
        log.warning("no usable local token key; linked accounts are not offered")
        return None


def registry(settings: Settings, cipher: TokenCipher | None) -> dict[c.Provider, ProviderInfo]:
    """Returns every provider with whether it is offered, and why not."""
    configs = {
        c.Provider.LISTENBRAINZ: ProviderConfig(
            "listenbrainz", api_url=settings.listenbrainz_api_url
        ),
        c.Provider.LASTFM: ProviderConfig(
            settings.lastfm_api_key, settings.lastfm_secret, settings.lastfm_api_url
        ),
        c.Provider.LIBREFM: ProviderConfig(
            settings.librefm_api_key, settings.librefm_secret, settings.librefm_api_url
        ),
        c.Provider.SPOTIFY: ProviderConfig(settings.spotify_client_id),
        c.Provider.DEEZER: ProviderConfig(settings.deezer_app_id, settings.deezer_secret),
        c.Provider.APPLE_MUSIC: ProviderConfig(settings.apple_music_developer_token),
        c.Provider.YOUTUBE_MUSIC: ProviderConfig(
            settings.google_client_id, settings.google_client_secret
        ),
    }
    connectors: dict[c.Provider, c.Connector | None] = {
        c.Provider.LISTENBRAINZ: c.ListenBrainzConnector(settings.listenbrainz_api_url),
        c.Provider.LASTFM: c.LastFmConnector(c.Provider.LASTFM, settings.lastfm_api_url),
        c.Provider.LIBREFM: c.LastFmConnector(c.Provider.LIBREFM, settings.librefm_api_url),
        c.Provider.SPOTIFY: c.SpotifyConnector(),
        c.Provider.DEEZER: c.DeezerConnector(),
        c.Provider.APPLE_MUSIC: c.AppleMusicConnector(),
        c.Provider.YOUTUBE_MUSIC: c.YouTubeConnector(),
    }
    # YouTube Music links through Google when a client is configured (liked songs);
    # otherwise the listener imports a Takeout file on the device, which needs no keys.
    youtube = configs[c.Provider.YOUTUBE_MUSIC]
    youtube_linkable = bool(youtube.client_id and youtube.client_secret) and cipher is not None
    methods = {
        c.Provider.LISTENBRAINZ: Method.TOKEN,
        c.Provider.APPLE_MUSIC: Method.MUSICKIT,
        c.Provider.YOUTUBE_MUSIC: Method.REDIRECT if youtube_linkable else Method.FILE,
    }
    out = {}
    for provider, config in configs.items():
        method = methods.get(provider, Method.REDIRECT)
        if method is Method.FILE:
            available, reason = True, ""
        elif cipher is None:
            available, reason = False, "TOKEN_KEYS_NOT_CONFIGURED"
        elif not config.configured:
            available, reason = False, "PROVIDER_NOT_CONFIGURED"
        else:
            available, reason = True, ""
        out[provider] = ProviderInfo(
            provider, method, config, connectors[provider], available, reason
        )
    return out


def redirect_uri(settings: Settings, provider: c.Provider) -> str:
    """Where the provider sends the listener back (the app's /v1 proxy reaches the API)."""
    return f"{settings.app_origin.rstrip('/')}/v1/oauth/{provider.value.lower()}/callback"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _context(user_id: str, provider: c.Provider | str) -> str:
    return f"users/{user_id}/{provider}"


def start(
    session: Session,
    settings: Settings,
    cipher: TokenCipher,
    info: ProviderInfo,
    *,
    user_id: str,
    session_token: str,
    now: datetime,
) -> str:
    """Starts a redirect link and returns the provider's authorization URL."""
    state = new_state()
    verifier, challenge = pkce_pair()
    state_hash = _hash(state)
    repo.add_flow(
        session,
        m.OAuthFlow(
            state_hash=state_hash,
            user_id=user_id,
            session_hash=_hash(session_token),
            provider=info.provider.value,
            verifier_ciphertext=cipher.encrypt(verifier, context=f"flows/{state_hash}"),
            expires_at=now + timedelta(seconds=STATE_TTL_S),
        ),
    )
    return authorization_url(
        info.provider,
        info.config,
        redirect_uri=redirect_uri(settings, info.provider),
        state=state,
        challenge=challenge,
    )


def _store(
    session: Session,
    cipher: TokenCipher,
    *,
    user_id: str,
    provider: c.Provider,
    linked: Linked,
    now: datetime,
) -> m.LinkedAccount:
    """Saves a link; relinking the same external account keeps its history and cursor."""
    context = _context(user_id, provider)
    row = repo.get_account(session, user_id, provider.value)
    if row is not None and row.external_user != linked.external_user:
        repo.unlink(session, user_id, provider.value)  # a different account: start over
        session.flush()
        row = None
    expires = None if linked.expires_at is None else datetime.fromtimestamp(linked.expires_at, UTC)
    if row is None:
        row = m.LinkedAccount(
            user_id=user_id,
            provider=provider.value,
            external_user=linked.external_user,
            cursor=None,
            linked_at=now,
            failures=0,
            unmatched_plays=0,
        )
        session.add(row)
    row.token_ciphertext = cipher.encrypt(linked.access_token, context=context)
    row.refresh_ciphertext = (
        cipher.encrypt(linked.refresh_token, context=context) if linked.refresh_token else None
    )
    row.token_expires_at = expires
    row.status = ACTIVE
    row.last_error = None
    row.failures = 0
    row.next_sync_after = now
    return row


def finish(
    session: Session,
    http: httpx.Client,
    settings: Settings,
    cipher: TokenCipher,
    info: ProviderInfo,
    *,
    state: str,
    code: str,
    session_token: str | None,
    now: datetime,
) -> m.LinkedAccount:
    """Completes a redirect link.

    Raises:
        LinkError: Unknown, expired, reused or foreign state; or the provider refused.
    """
    flow = repo.take_flow(session, _hash(state), now)
    if flow is None or flow.provider != info.provider.value:
        raise LinkError("LINK_STATE_INVALID", "This link request expired or was already used.")
    if session_token is None or _hash(session_token) != flow.session_hash:
        raise LinkError("LINK_STATE_INVALID", "This link was started in another session.")
    try:
        verifier = cipher.decrypt(flow.verifier_ciphertext, context=f"flows/{flow.state_hash}")
        linked = complete(
            http,
            info.provider,
            info.config,
            code=code,
            redirect_uri=redirect_uri(settings, info.provider),
            verifier=verifier,
        )
    except (c.ConnectorError, TokenCipherError) as exc:
        raise LinkError("LINK_REFUSED", f"{info.provider} did not complete the link.") from exc
    return _store(
        session, cipher, user_id=flow.user_id, provider=info.provider, linked=linked, now=now
    )


def link_with_token(
    session: Session,
    http: httpx.Client,
    cipher: TokenCipher,
    info: ProviderInfo,
    *,
    user_id: str,
    token: str,
    now: datetime,
) -> m.LinkedAccount:
    """Links a token-based provider (ListenBrainz) or an Apple Music user token.

    Raises:
        LinkError: The provider rejected the token, or the provider does not take tokens.
    """
    if info.provider is c.Provider.LISTENBRAINZ:
        try:
            linked = validate_listenbrainz_token(http, info.config.api_url, token)
        except c.ConnectorError as exc:
            raise LinkError("LINK_REFUSED", "ListenBrainz did not accept the token.") from exc
    elif info.provider is c.Provider.APPLE_MUSIC:
        linked = Linked(external_user="apple-music", access_token=token)
    else:
        raise LinkError("LINK_METHOD_INVALID", f"{info.provider} links through its own site.")
    return _store(session, cipher, user_id=user_id, provider=info.provider, linked=linked, now=now)


@dataclass(frozen=True)
class SyncOutcome:
    """What one sync did."""

    plays: int
    artists: int
    unmatched: int
    status: str
    error: str | None = None


def _credentials(
    account: m.LinkedAccount,
    info: ProviderInfo,
    cipher: TokenCipher,
    *,
    http: httpx.Client,
    now: datetime,
) -> c.Credentials:
    context = _context(account.user_id, account.provider)
    token = cipher.decrypt(account.token_ciphertext, context=context)
    expires = account.token_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    # Refresh a minute early, so a token does not expire in the middle of a sync.
    if info.provider in REFRESHABLE and expires is not None and expires <= now + EXPIRY_MARGIN:
        if not account.refresh_ciphertext:
            raise c.RevokedError(f"{info.provider} access expired and cannot be refreshed")
        refreshed = refresh(
            http,
            info.provider,
            info.config,
            cipher.decrypt(account.refresh_ciphertext, context=context),
        )
        token = refreshed.access_token
        account.token_ciphertext = cipher.encrypt(token, context=context)
        account.refresh_ciphertext = cipher.encrypt(refreshed.refresh_token, context=context)
        account.token_expires_at = (
            None
            if refreshed.expires_at is None
            else datetime.fromtimestamp(refreshed.expires_at, UTC)
        )
    extra = {"api_key": info.config.client_id}
    if info.provider is c.Provider.APPLE_MUSIC:
        extra = {"developer_token": info.config.client_id}
    return c.Credentials(external_user=account.external_user, access_token=token, extra=extra)


def sync_account(
    session: Session,
    http: httpx.Client,
    settings: Settings,
    cipher: TokenCipher,
    *,
    info: ProviderInfo,
    account: m.LinkedAccount,
    known_artists: Callable[[str], bool],
    resolve_names: Callable[[Sequence[str]], Sequence[str | None]],
    now: datetime,
) -> SyncOutcome:
    """Reads new plays, adds them to the account's tallies, and schedules the next sync.

    Failures never raise: a revoked link is marked NEEDS_RELINK; other failures
    back off exponentially (capped at a day) and are retried by the job.
    """
    interval = timedelta(minutes=settings.sync_interval_minutes)
    if info.connector is None:
        return SyncOutcome(0, 0, 0, account.status, "NO_CONNECTOR")
    total_plays = unmatched = 0
    tallies: dict[str, Tally] = {}
    try:
        credentials = _credentials(account, info, cipher, http=http, now=now)
        cursor = account.cursor
        for _ in range(MAX_PAGES_PER_SYNC):
            page = info.connector.fetch(http, credentials, cursor)
            result = aggregate(page.plays, known_artists, resolve_names)
            total_plays += len(page.plays)
            unmatched += result.unmatched_plays
            for artist_id, tally in result.tallies.items():
                tallies[artist_id] = merge(tallies.get(artist_id), tally)
            cursor = page.cursor
            if not page.more:
                break
    except c.RevokedError:
        account.status = NEEDS_RELINK
        account.last_error = "REVOKED"
        log.info("linked account revoked", extra={"provider": account.provider})
        return SyncOutcome(0, 0, 0, NEEDS_RELINK, "REVOKED")
    except (c.ConnectorError, TokenCipherError) as exc:
        account.failures += 1
        account.last_error = type(exc).__name__
        account.next_sync_after = now + min(interval * 2 ** min(account.failures, 7), MAX_BACKOFF)
        log.warning(
            "linked account sync failed",
            extra={"provider": account.provider, "failures": account.failures},
        )
        return SyncOutcome(0, 0, 0, account.status, account.last_error)

    stored = repo.tallies(session, account.user_id, account.provider)
    rows = {}
    for artist_id, tally in tallies.items():
        previous = stored.get(artist_id)
        before = (
            None
            if previous is None
            else Tally(
                previous.plays,
                None
                if previous.last_played_at is None
                else int(previous.last_played_at.replace(tzinfo=UTC).timestamp()),
            )
        )
        combined = merge(before, tally)
        rows[artist_id] = (
            combined.plays,
            None
            if combined.last_played_at is None
            else datetime.fromtimestamp(combined.last_played_at, UTC),
        )
    repo.save_tallies(session, account.user_id, account.provider, rows)
    account.cursor = cursor
    account.unmatched_plays += unmatched
    account.last_sync_at = now
    account.failures = 0
    account.last_error = None
    account.next_sync_after = now + interval
    return SyncOutcome(total_plays, len(tallies), unmatched, account.status)


def sync_due(
    session: Session,
    http: httpx.Client,
    settings: Settings,
    cipher: TokenCipher,
    *,
    known_artists: Callable[[str], bool],
    resolve_names: Callable[[Sequence[str]], Sequence[str | None]],
    now: datetime,
    limit: int = 500,
) -> dict[str, int]:
    """Syncs every account whose next sync is due (the scheduled job) and returns counts.

    One account's failure never stops the others: ``sync_account`` records it on
    the account and backs off.
    """
    offered = registry(settings, cipher)
    counts = {"accounts": 0, "plays": 0, "failed": 0, "needRelink": 0, "skipped": 0}
    for account in repo.due_accounts(session, now, limit):
        info = offered.get(c.Provider(account.provider))
        if info is None or not info.available or info.connector is None:
            counts["skipped"] += 1  # the provider's keys were removed: leave the account alone
            continue
        outcome = sync_account(
            session,
            http,
            settings,
            cipher,
            info=info,
            account=account,
            known_artists=known_artists,
            resolve_names=resolve_names,
            now=now,
        )
        counts["accounts"] += 1
        counts["plays"] += outcome.plays
        if outcome.status == NEEDS_RELINK:
            counts["needRelink"] += 1
        elif outcome.error:
            counts["failed"] += 1
    counts["expiredFlows"] = repo.purge_flows(session, now)
    return counts
