"""Copy a quiesced database into an empty, migrated destination without deleting source data."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, Engine, Integer, Table, func, inspect, select, text

from songnexus.storage import migrate
from songnexus.storage.models import Base


def _reset_sequence(destination: Connection, table: Table) -> None:
    if destination.dialect.name != "postgresql" or len(table.primary_key.columns) != 1:
        return
    column = next(iter(table.primary_key.columns))
    if not isinstance(column.type, Integer):
        return
    sequence = destination.scalar(
        text("SELECT pg_get_serial_sequence(:table, :column)"),
        {"table": table.name, "column": column.name},
    )
    if sequence:
        maximum = destination.scalar(select(func.max(column)))
        destination.execute(
            text("SELECT setval(CAST(:sequence AS regclass), :value, :called)"),
            {"sequence": sequence, "value": maximum or 1, "called": maximum is not None},
        )


def transfer(source: Engine, target: Engine, *, apply: bool = False) -> dict[str, Any]:
    """Inspect or copy all application tables; refuse occupied or incompatible databases.

    Stop writers before running. The source must already be migrated to head.
    Schema creation is separate from the transactional data copy; failed copies
    leave an empty migrated target which can safely be retried.

    Raises:
        ValueError: A database is incompatible or the destination is not empty.
    """
    if source.url == target.url:
        raise ValueError("Source and destination must be different databases")
    if migrate.current_revision(source) != migrate.head_revision(source):
        raise ValueError("Migrate the source to head before transferring")
    tables = Base.metadata.sorted_tables
    existing = set(inspect(target).get_table_names())
    expected = {t.name for t in tables} | {"alembic_version"}
    if existing - expected:
        raise ValueError("Destination contains unrelated tables; use a dedicated empty database")
    with target.connect() as connection:
        for table in tables:
            if table.name in existing and connection.scalar(
                select(func.count()).select_from(table)
            ):
                raise ValueError(f"Destination table {table.name} is not empty")
    with source.connect() as origin:
        counts = {
            t.name: int(origin.scalar(select(func.count()).select_from(t)) or 0) for t in tables
        }
    if not apply:
        return {"dryRun": True, "tables": counts, "rows": sum(counts.values())}
    migrate.upgrade(target)
    copied: dict[str, int] = {}
    with source.connect() as origin, origin.begin(), target.begin() as destination:
        # Serialize transfers on PostgreSQL and exclude concurrent application writes.
        if target.dialect.name == "postgresql":
            names = ", ".join(target.dialect.identifier_preparer.quote(t.name) for t in tables)
            destination.execute(text(f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE"))
        for table in tables:
            if destination.scalar(select(func.count()).select_from(table)):
                raise ValueError(f"Destination table {table.name} is not empty")
        for table in tables:
            count = 0
            result = origin.execution_options(stream_results=True).execute(select(table))
            for partition in result.mappings().partitions(500):
                rows = [dict(row) for row in partition]
                destination.execute(table.insert(), rows)
                count += len(rows)
            if destination.scalar(select(func.count()).select_from(table)) != count:
                raise ValueError(f"Row verification failed for {table.name}")
            copied[table.name] = count
            _reset_sequence(destination, table)
    return {"dryRun": False, "tables": copied, "rows": sum(copied.values()), "verified": True}
