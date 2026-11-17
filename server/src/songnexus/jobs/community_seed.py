"""Development only: synthetic Around you members, so a community chart can be demoed.

``songnexus seed-community --campus <slug> --listeners N`` creates N clearly
synthetic accounts (no sign-in identity, membership marked ``synthetic``) whose
tallies are drawn from the real catalog, weighted by public ListenBrainz audience
sizes, with a per-community taste so campuses differ. A chart dated eight days
earlier is stored too (without a few "rising" artists), so movement and rising
can be shown. Charts built from them say "demo data", synthetic members only
count in development, and ``--remove`` deletes them and the charts they fed.

It refuses to run outside development and never runs automatically.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from sqlalchemy import Engine

from songnexus.core import community as core
from songnexus.storage import community_repository as repo
from songnexus.storage.db import session_scope

MAX_LISTENERS = 500
POOL = 400
FAVORITES = 25
RISERS = 5
BASELINE_AGE = timedelta(days=8)
# Fewer catalog artists than this and the demo would not look like listening.
MIN_POOL = FAVORITES + RISERS + 10
# Share of plays from this week, of members who play each riser, and of members in
# the week-old baseline (so the chart visibly grows).
RECENT_SHARE = 0.5
RISER_SHARE = 0.45
BASELINE_SHARE = 0.85


class SeedRefusedError(RuntimeError):
    """Seeding is not allowed here (wrong environment, bad arguments, empty catalog)."""


def check_environment(environment: str) -> None:
    """Refuses anything but development.

    Raises:
        SeedRefusedError: Not development.
    """
    if environment != "development":
        raise SeedRefusedError(
            f"seed-community only runs in development (SONGNEXUS_ENVIRONMENT is {environment!r})"
        )


def seed_community(
    engine: Engine,
    environment: str,
    community: core.Community,
    listeners: int,
    now: datetime,
) -> dict[str, int | str]:
    """Creates synthetic members of ``community`` and a week-old baseline chart.

    Raises:
        SeedRefusedError: Outside development, a bad listener count, or a catalog
            too small to draw from.
    """
    check_environment(environment)
    if not 1 <= listeners <= MAX_LISTENERS:
        raise SeedRefusedError(f"--listeners must be between 1 and {MAX_LISTENERS}")
    # Seeded per community, so a re-run gives the same demo. Not used for security.
    rng = random.Random(f"songnexus-demo:{community.id}")  # noqa: S311
    with session_scope(engine) as session:
        pool = repo.catalog_artists_by_audience(session, POOL)
    if len(pool) < MIN_POOL:
        raise SeedRefusedError("the catalog is too small to draw demo listening from")
    ids = [a for a, _ in pool]
    favorites = set(rng.sample(ids, min(FAVORITES, len(ids))))
    risers = rng.sample([a for a in ids if a not in favorites], min(RISERS, len(ids) // 4))
    weights = [
        ((n + 50) ** 0.5) * (8.0 if a in favorites else 1.0) for a, n in pool if a not in risers
    ]
    steady = [a for a in ids if a not in risers]

    members: list[dict[str, tuple[int, datetime | None]]] = []
    for _ in range(listeners):
        picks: set[str] = set()
        want = min(rng.randint(12, 35), len(steady))
        while len(picks) < want:
            picks.add(rng.choices(steady, weights=weights)[0])
        tallies: dict[str, tuple[int, datetime | None]] = {}
        for artist_id in picks:
            days = rng.uniform(0, 7) if rng.random() < RECENT_SHARE else rng.uniform(8, 60)
            tallies[artist_id] = (rng.randint(1, 80), now - timedelta(days=days))
        for artist_id in risers:
            if rng.random() < RISER_SHARE:
                tallies[artist_id] = (rng.randint(3, 40), now - timedelta(days=rng.uniform(0, 5)))
        members.append(tallies)

    baseline_at = now - BASELINE_AGE
    baseline = core.compute_chart(
        (
            core.Tally(i, artist_id, plays, last)
            for i, tallies in enumerate(members)
            if rng.random() < BASELINE_SHARE
            for artist_id, (plays, last) in tallies.items()
            if artist_id not in risers
        ),
        known=lambda _a: True,
        genres_of=lambda _a: (),
        now=baseline_at,
        demo=True,
    )
    with session_scope(engine) as session:
        repo.delete_charts(session, [community.id])
        for tallies in members:
            repo.add_synthetic_member(session, community.kind.value, community.id, tallies, now)
        repo.save_chart(session, community.id, baseline_at, baseline.to_payload())
    return {"community": community.id, "syntheticListeners": listeners}


def remove_synthetic(engine: Engine, environment: str, community_id: str | None) -> dict[str, int]:
    """Deletes synthetic members (of one community, or all) and the charts they fed.

    Raises:
        SeedRefusedError: Outside development.
    """
    check_environment(environment)
    with session_scope(engine) as session:
        removed, communities = repo.remove_synthetic(session, community_id)
        charts = repo.delete_charts(session, communities)
    return {"removedListeners": removed, "removedCharts": charts}
