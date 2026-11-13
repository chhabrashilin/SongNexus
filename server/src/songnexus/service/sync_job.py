"""Sync job: reads new plays for every linked account that is due (ADR 0006, decision 5).

Scheduled every 15 minutes (Cloud Scheduler -> Cloud Run job ``songnexus-sync``).
Each account is committed on its own, so one failure or a crash mid-run never
loses the others' progress, and a second run simply continues.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from sqlalchemy import Engine

from songnexus.config import Settings
from songnexus.core.resolution import Decision
from songnexus.service import linking
from songnexus.service.readmodel import ReadModel
from songnexus.storage.db import session_scope

BATCH = 50


def run_sync(
    engine: Engine,
    settings: Settings,
    model: ReadModel,
    http: httpx.Client,
    *,
    now: datetime | None = None,
    max_batches: int = 20,
) -> dict[str, int]:
    """Syncs due accounts in batches and returns what happened."""
    cipher = linking.cipher_from(settings)
    totals = {"accounts": 0, "plays": 0, "failed": 0, "needRelink": 0, "skipped": 0}
    if cipher is None:
        return totals
    now = now or datetime.now(UTC)

    def resolve(names: list[str]) -> list[str | None]:
        return [
            r.entity_id if r.decision is Decision.MATCHED else None
            for r in model.resolutions.resolve(model.search, list(names))
        ]

    for _ in range(max_batches):
        with session_scope(engine) as session:
            counts = linking.sync_due(
                session,
                http,
                settings,
                cipher,
                known_artists=lambda artist: artist in model.graph.nodes,
                resolve_names=resolve,  # type: ignore[arg-type]
                now=now,
                limit=BATCH,
            )
        for key in totals:
            totals[key] += counts.get(key, 0)
        # Synced and failed accounts move their next sync forward; skipped ones do not,
        # so stop when a batch made no progress.
        if counts["accounts"] == 0:
            break
    return totals
