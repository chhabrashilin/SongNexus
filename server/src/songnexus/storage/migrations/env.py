"""Alembic environment: runs migrations on the engine passed in by ``migrate.py``."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Engine

from songnexus.storage.models import Base

engine: Engine = context.config.attributes["engine"]

with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        # SQLite cannot ALTER most things; batch mode rebuilds tables instead.
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
    connection.commit()
