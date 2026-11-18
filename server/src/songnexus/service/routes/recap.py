"""Weekly campus recap: what rose, fell, entered and left a community chart this week.

Computed from stored chart snapshots (one per community per day, kept 35 days,
see ``community_job``): the current chart against the newest unlocked chart at
least a week old. Both are already past the privacy floors, so the recap adds
no new information about anyone. Under the ``community`` flag.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from songnexus.core import community as core
from songnexus.service import community_job, convert
from songnexus.service import schemas_games as games_api
from songnexus.service.deps import Viewer, app_state, rate_limited, read_model, viewer
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes.common import db_session, set_cache_control
from songnexus.service.routes.community import _community, _enabled, _time, community_resource

router = APIRouter(
    prefix="/v1", tags=["community"], dependencies=[Depends(rate_limited(MethodClass.READ))]
)

ViewerDep = Annotated[Viewer, Depends(viewer)]
SessionDep = Annotated[Session, Depends(db_session, scope="function")]
ModelDep = Annotated[ReadModel, Depends(read_model)]


@router.get(
    "/communities/{community:rid}/weeklyMovers",
    response_model=games_api.WeeklyMovers,
    summary="GetWeeklyMovers",
)
def get_weekly_movers(
    community: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ModelDep,
) -> games_api.WeeklyMovers:
    """The chart's biggest rises and falls, new entries and exits since a week ago.

    LOCKED while the chart is locked; NO_HISTORY until an unlocked chart from at
    least seven days ago is stored. The viewer's blocked artists are left out.
    """
    _enabled(request)
    found = _community(community)
    now = datetime.now(UTC)
    view = community_job.chart_view(session, app_state(request).settings, model, found.id, now)
    previous = core.baseline(view.history, now) if view.chart.unlocked else None
    graph = model.graph

    def rows(movers: tuple[core.Mover, ...]) -> list[games_api.ChartMover]:
        return [
            games_api.ChartMover(
                artist=convert.artist_summary(graph, m.artist_id),
                rank=m.rank,
                previous_rank=m.previous_rank,
                places=m.places,
            )
            for m in movers
            if m.artist_id in graph.nodes and m.artist_id not in who.blocked
        ]

    if not view.chart.unlocked:
        state = games_api.MoversState.LOCKED
    elif previous is None:
        state = games_api.MoversState.NO_HISTORY
    else:
        state = games_api.MoversState.AVAILABLE
    moved = core.weekly_movers(view.chart, previous) if previous is not None else None
    set_cache_control(response, who)
    return games_api.WeeklyMovers(
        name=f"communities/{found.id}/weeklyMovers",
        community=community_resource(found),
        state=state,
        rose=rows(moved.rose) if moved else [],
        fell=rows(moved.fell) if moved else [],
        entered=rows(moved.entered) if moved else [],
        left=rows(moved.left) if moved else [],
        update_time=_time(view.chart.computed_at),
        previous_update_time=_time(previous.computed_at) if previous else None,
        demo_data=view.chart.demo or bool(previous and previous.demo),
        graph_version=model.version,
    )
