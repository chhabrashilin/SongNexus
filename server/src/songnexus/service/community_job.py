"""Community charts: computed per community, cached in the database with a TTL.

A chart is never computed per request over all users. Reading a chart returns
the stored one while it is fresh; a stale or missing chart is recomputed from
that one community's members only (lazily), and ``songnexus community-charts``
recomputes every stale chart on a schedule (Cloud Scheduler -> Cloud Run job
``songnexus-community``, hourly), like the sync job. Each community commits on
its own, so one failure never blocks the others.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from songnexus.config import Settings
from songnexus.core import community as core
from songnexus.service.readmodel import ReadModel
from songnexus.storage import community_repository as repo
from songnexus.storage.db import session_scope

# Charts are kept a day apart for this long: a week plus the 28-day rising window.
HISTORY_RETENTION = core.RECENT + core.HISTORY


@dataclass(frozen=True)
class ChartView:
    """A chart with what it is compared against."""

    chart: core.Chart
    history: tuple[core.Chart, ...]
    next_update: datetime


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# A locked chart shows only how many more listeners it needs, so it refreshes
# sooner: someone who just joined sees the count move within minutes.
LOCKED_TTL = timedelta(minutes=5)


def _ttl(settings: Settings, chart: core.Chart) -> timedelta:
    full = timedelta(minutes=settings.community_chart_ttl_minutes)
    return full if chart.unlocked else min(full, LOCKED_TTL)


def include_synthetic(settings: Settings) -> bool:
    """Synthetic demo members count only in development."""
    return settings.environment == "development"


def compute(
    session: Session, settings: Settings, model: ReadModel, community_id: str, now: datetime
) -> core.Chart:
    """Computes one community's chart from its members' tallies and stores it."""
    rows, synthetic = repo.member_tallies(
        session, community_id, include_synthetic=include_synthetic(settings)
    )
    graph = model.graph

    def genres_of(artist_id: str) -> list[str]:
        node = graph.nodes.get(artist_id)
        if node is None:
            return []
        return [g.genre_id for g in sorted(node.genres, key=lambda g: -g.share)]

    chart = core.compute_chart(
        (core.Tally(*row) for row in rows),
        known=lambda a: a in graph.nodes,
        genres_of=genres_of,
        now=now,
        demo=synthetic,
    )
    repo.save_chart(session, community_id, now, chart.to_payload())
    return chart


def chart_view(
    session: Session,
    settings: Settings,
    model: ReadModel,
    community_id: str,
    now: datetime | None = None,
) -> ChartView:
    """Returns the community's chart, recomputing it when stale, with its history."""
    now = now or datetime.now(UTC)
    stored = repo.charts(session, community_id, now - HISTORY_RETENTION)
    latest = stored[0] if stored else None
    cached = core.Chart.from_payload(latest.payload, _utc(latest.computed_at)) if latest else None
    if cached is not None and now - cached.computed_at < _ttl(settings, cached):
        chart = cached
        older = stored[1:]
    else:
        chart = compute(session, settings, model, community_id, now)
        older = [s for s in stored if _utc(s.computed_at).date() != now.date()]
    history = tuple(core.Chart.from_payload(s.payload, _utc(s.computed_at)) for s in older)
    return ChartView(chart, history, chart.computed_at + _ttl(settings, chart))


def run_community_charts(
    engine: Engine, settings: Settings, model: ReadModel, *, now: datetime | None = None
) -> dict[str, int]:
    """Recomputes every stale chart of a community with members; returns counts."""
    now = now or datetime.now(UTC)
    with session_scope(engine) as session:
        ids = repo.communities_with_members(session)
    totals = {"communities": len(ids), "recomputed": 0, "unlocked": 0}
    for community_id in ids:
        with session_scope(engine) as session:
            latest = repo.latest_chart(session, community_id)
            cached = (
                core.Chart.from_payload(latest.payload, _utc(latest.computed_at))
                if latest
                else None
            )
            if cached is not None and now - cached.computed_at < _ttl(settings, cached):
                chart = cached
            else:
                chart = compute(session, settings, model, community_id, now)
                totals["recomputed"] += 1
        totals["unlocked"] += int(chart.unlocked)
    return totals
