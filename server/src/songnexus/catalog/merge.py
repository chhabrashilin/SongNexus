"""Combine independently fetched MusicBrainz snapshots without dropping older entities."""

from __future__ import annotations

from pathlib import Path

from songnexus.catalog.snapshot import RawRecord, read_snapshot, write_snapshot

MIN_INPUTS = 2


def merge_snapshots(paths: list[Path], output: Path) -> dict[str, int]:
    """Write a union by kind/request key; later input wins on conflicts.

    The output must be new. This keeps committed inputs and the active catalog
    intact until the merged snapshot has passed normal ingestion quality gates.

    Raises:
        ValueError: Fewer than two inputs or an existing output is supplied.
    """
    if len(paths) < MIN_INPUTS or output.exists():
        raise ValueError("Supply at least two inputs and a new output path")
    records: dict[tuple[str, str], RawRecord] = {}
    replaced = 0
    for path in paths:
        for record in read_snapshot(path):
            key = record.kind, record.request_key
            replaced += key in records
            records[key] = record
    count = write_snapshot(records.values(), output)
    return {"records": count, "replaced": replaced, "inputs": len(paths)}
