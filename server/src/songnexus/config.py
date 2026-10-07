"""Process configuration, read from environment variables prefixed ``SONGNEXUS_``.

Paths never depend on where the package is installed (a v0 bug): the data
directory is configured explicitly, or discovered from the working directory.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    """Returns ``./data`` or ``../data``, whichever exists (repo root or ``server/``)."""
    for candidate in (Path.cwd() / "data", Path.cwd().parent / "data"):
        if (candidate / "samples").is_dir():
            return candidate
    return Path.cwd() / "data"


class Settings(BaseSettings):
    """All runtime settings. Every field can be set as ``SONGNEXUS_<FIELD>``."""

    model_config = SettingsConfigDict(env_prefix="SONGNEXUS_", env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+psycopg://songnexus:songnexus@127.0.0.1:5432/songnexus"
    data_dir: Path = Field(default_factory=_default_data_dir)
    log_level: str = "INFO"
    log_json: bool = True

    # Service.
    gcp_project: str = Field(default="", validation_alias="GOOGLE_CLOUD_PROJECT")
    flags: dict[str, bool] = Field(default_factory=dict)
    trusted_proxy_hops: int = 1
    read_model_refresh_s: float = 60.0
    rate_limit_read_per_minute: int = 600
    rate_limit_analyze_per_minute: int = 120
    rate_limit_write_per_minute: int = 60

    # Identity (ADR 0002).
    firebase_project_id: str = ""
    session_ttl_days: int = 14
    # Origins allowed to make state-changing requests (CSRF defense, with the token).
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # MusicBrainz asks clients to identify themselves; the contact is optional.
    musicbrainz_base_url: str = "https://musicbrainz.org/ws/2"
    musicbrainz_contact: str = ""
    musicbrainz_min_interval_s: float = 1.1

    @property
    def snapshot_path(self) -> Path:
        """The committed catalog snapshot that ingestion reads."""
        return self.data_dir / "samples" / "musicbrainz_snapshot.jsonl.gz"

    @property
    def seeds_path(self) -> Path:
        """The seed-artist list that the fetch pipeline expands."""
        return self.data_dir / "seeds" / "seed_artists.json"

    @property
    def raw_cache_dir(self) -> Path:
        """Local HTTP cache for the fetch pipeline (git-ignored)."""
        return self.data_dir / "raw" / "musicbrainz"


class ConfigError(RuntimeError):
    """The configuration is unsafe or incomplete for this environment."""


def validate_for_serving(settings: Settings, env: Mapping[str, str]) -> None:
    """Refuses configurations that would break or weaken a deployed service.

    Development is exempt. Everywhere else (staging, demo): writes need real
    HTTPS origins, sign-in needs a Firebase project, and the Auth emulator,
    which makes the Admin SDK accept unsigned tokens, must not be configured.

    Raises:
        ConfigError: Listing every problem found.
    """
    if settings.environment == "development":
        return
    problems = []
    if not settings.allowed_origins or any(
        not origin.startswith("https://") for origin in settings.allowed_origins
    ):
        problems.append("SONGNEXUS_ALLOWED_ORIGINS must list the app's https:// origins")
    if not settings.firebase_project_id:
        problems.append("SONGNEXUS_FIREBASE_PROJECT_ID is required for sign-in")
    if env.get("FIREBASE_AUTH_EMULATOR_HOST"):
        problems.append("FIREBASE_AUTH_EMULATOR_HOST must not be set outside development")
    if problems:
        raise ConfigError("; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    """Returns the process-wide settings (cached)."""
    return Settings()
