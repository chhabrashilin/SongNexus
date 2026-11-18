"""Z-star at serving time: cached artifacts and listener signals (ADR 0010).

- The catalog view and the artist embeddings are derived once per catalog
  version (kept in the read model's memo). Embeddings are read from storage
  when the ``zstar-embed`` job has built them for this version; otherwise they
  are built here once (a few seconds) and stored for the other instances.
- The ranking model is the active ``ranker`` artifact, re-checked at most once
  a minute so a newly promoted model reaches every instance without a restart.
  Without one, the documented prior serves.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from songnexus.core.browse import BrowseIndex
from songnexus.core.zstar.catalog import Catalog, build_catalog
from songnexus.core.zstar.embed import Embeddings, build_embeddings
from songnexus.core.zstar.ranker import PRIOR, Model
from songnexus.core.zstar.signals import Engagement, Signals
from songnexus.service.readmodel import ReadModel
from songnexus.storage import models as m
from songnexus.storage import user_repository as users
from songnexus.storage import zstar_repository as zr

log = logging.getLogger(__name__)
RANKER_CHECK_S = 60.0


def catalog_view(model: ReadModel, index: BrowseIndex) -> Catalog:
    """The Z-star catalog view for this read model's catalog version."""
    return model.memo.get("zstar_catalog", lambda: build_catalog(index))


def compute_embeddings(catalog: Catalog) -> Embeddings:
    """Builds embeddings from a catalog view (the job and the fallback both use this)."""
    genres = {a: list(g.items()) for a, g in catalog.genres.items()}
    return build_embeddings(catalog.adjacency, catalog.colistening, genres, catalog.version)


def embeddings_for(model: ReadModel, catalog: Catalog, session: Session) -> Embeddings | None:
    """Artist embeddings for this catalog version (stored, or built once and stored)."""

    def load() -> Embeddings | None:
        stored = zr.artifact(session, "embeddings", catalog.version)
        if stored is not None:
            return Embeddings.from_payload(stored.payload)
        started = time.monotonic()
        try:
            built = compute_embeddings(catalog)
        except Exception:  # serving continues without the embedding source
            log.exception("zstar.embeddings.failed", extra={"version": catalog.version})
            return None
        log.info(
            "zstar.embeddings.built",
            extra={"version": catalog.version, "seconds": round(time.monotonic() - started, 2)},
        )
        try:
            zr.put_artifact(
                session,
                "embeddings",
                catalog.version,
                payload=built.to_payload(),
                metrics={"artists": len(built.ids)},
                now=datetime.now(UTC),
            )
            session.flush()
        except Exception:  # another instance stored it first; ours is identical
            log.info("zstar.embeddings.store_skipped", extra={"version": catalog.version})
        return built

    return model.memo.get("zstar_embeddings", load)


class RankerCache:
    """The active ranking model, re-checked at most every ``RANKER_CHECK_S`` seconds."""

    def __init__(self) -> None:
        self._model: Model = PRIOR
        self._checked = float("-inf")
        self._lock = threading.Lock()

    def current(self, session: Session) -> Model:
        """The model to rank with (the prior when none is active or loading fails)."""
        now = time.monotonic()
        with self._lock:
            if now - self._checked < RANKER_CHECK_S:
                return self._model
            self._checked = now
        try:
            version = zr.active_version(session, "ranker")
            if version is None:
                model = PRIOR
            elif version == self._model.version:
                return self._model
            else:
                row = zr.artifact(session, "ranker", version)
                model = PRIOR if row is None else Model.from_payload(row.payload)
        except Exception:  # keep serving with what we have
            log.exception("zstar.ranker.load_failed")
            return self._model
        with self._lock:
            self._model = model
        return model


RANKERS = RankerCache()


def _feedback_maps(
    rows: list[m.TasteFeedback],
) -> tuple[dict[str, datetime], dict[str, datetime], dict[str, datetime]]:
    not_interested: dict[str, datetime] = {}
    more_like: dict[str, datetime] = {}
    less_genres: dict[str, datetime] = {}
    for row in rows:
        kind, _, ident = row.subject.partition("/")
        at = _aware(row.created_at)
        if row.kind == "NOT_INTERESTED" and kind == "artists":
            not_interested[ident] = at
        elif row.kind == "MORE_LIKE_THIS" and kind == "artists":
            more_like[ident] = at
        elif row.kind == "LESS_OF_GENRE" and kind == "genres":
            less_genres[ident] = at
    return not_interested, more_like, less_genres


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; everything here is UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def load_signals(session: Session, user_id: str, now: datetime) -> tuple[Signals, bool]:
    """Everything the recommender reads about one listener, and whether activity is used."""
    prefs = session.get(m.Preferences, user_id)
    personalize = prefs.personalize if prefs is not None else True
    profile = session.get(m.Profile, user_id)
    not_interested, more_like, less_genres = _feedback_maps(zr.feedback(session, user_id))
    engagement = (
        {
            a: Engagement(
                impressions=e.impressions,
                opens=e.opens,
                listens=e.listens,
                skips=e.skips,
                dwell_ms=e.dwell_ms,
                last_at=None if e.last_at is None else _aware(e.last_at),
                recent_impressions=e.recent_impressions,
            )
            for a, e in zr.engagement(session, user_id, now).items()
        }
        if personalize
        else {}
    )
    signals = Signals(
        now=now,
        follows={f.artist_id: _aware(f.created_at) for f in zr.follows(session, user_id)},
        plays={
            a: (n, None if last is None else _aware(last))
            for a, (n, last) in zr.plays(session, user_id).items()
        },
        top_artists=tuple(profile.top_artist_ids) if profile is not None else (),
        preferred_genres=tuple(prefs.genre_ids) if prefs is not None else (),
        more_like=more_like,
        not_interested=not_interested,
        less_genres=less_genres,
        blocked=frozenset(users.blocked_artist_ids(session, user_id)),
        engagement=engagement,
        friends=zr.friends_top_artists(session, user_id),
    )
    return signals, personalize
