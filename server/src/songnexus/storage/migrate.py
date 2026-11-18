"""Schema migrations (Alembic), driven from code rather than an ``alembic.ini``."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(engine: Engine) -> Config:
    """Returns an Alembic config bound to ``engine``."""
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    config.attributes["engine"] = engine
    return config


def upgrade(engine: Engine, revision: str = "head") -> None:
    """Migrates the database up to ``revision``."""
    command.upgrade(alembic_config(engine), revision)


def downgrade(engine: Engine, revision: str) -> None:
    """Migrates the database down to ``revision`` (``base`` for empty)."""
    command.downgrade(alembic_config(engine), revision)


def current_revision(engine: Engine) -> str | None:
    """Returns the revision the database is at, or None when unversioned."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def head_revision(engine: Engine) -> str | None:
    """Returns the newest revision in the migration scripts."""
    return ScriptDirectory.from_config(alembic_config(engine)).get_current_head()
