"""Engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from songnexus.core.config import get_settings
from songnexus.db.models import Base


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        in_memory = url in {"sqlite://", "sqlite:///:memory:"}
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            # An in-memory database lives in one connection; share it.
            poolclass=StaticPool if in_memory else None,
        )

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fks(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=5)


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


def create_all(engine: Engine) -> None:
    # Schema migrations (Alembic) are planned for Phase 1; see docs/roadmap.md.
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any error."""
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
