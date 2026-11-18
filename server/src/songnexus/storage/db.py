"""Engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from songnexus.storage.models import Base


def make_engine(url: str) -> Engine:
    """Creates an engine; SQLite gets foreign keys and a shared in-memory connection."""
    if url.startswith("sqlite"):
        in_memory = url in {"sqlite://", "sqlite:///:memory:"}
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool if in_memory else None,
        )

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fks(dbapi_conn: Any, _record: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=5)


def create_schema(engine: Engine) -> None:
    """Creates every table directly. For tests and throwaway SQLite databases only.

    Persistent databases are migrated with Alembic; a test asserts the two
    produce the same schema.
    """
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Yields a transactional session: commits on success, rolls back on error."""
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
