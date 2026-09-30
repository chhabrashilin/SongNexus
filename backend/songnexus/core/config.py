"""Application settings, loaded from environment variables (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SONGNEXUS_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = f"sqlite:///{(REPO_ROOT / 'data' / 'songnexus.db').as_posix()}"
    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    # Enables POST /api/v1/system/reload when non-empty. Never commit a value.
    admin_token: str = ""

    # Data locations
    sample_snapshot_path: Path = REPO_ROOT / "data" / "samples" / "musicbrainz_snapshot.jsonl.gz"
    raw_cache_dir: Path = REPO_ROOT / "data" / "raw" / "musicbrainz"
    seeds_path: Path = REPO_ROOT / "data" / "seeds" / "seed_artists.json"

    # MusicBrainz etiquette: a descriptive User-Agent with a contact is required.
    # The contact is deliberately configurable and empty by default.
    musicbrainz_base_url: str = "https://musicbrainz.org/ws/2"
    musicbrainz_contact: str = ""
    musicbrainz_min_interval_s: float = 1.1

    # Query limits (hard caps protect the service from unbounded work).
    max_neighbors: int = 150
    max_path_depth: int = 8
    max_alternative_paths: int = 5
    path_cache_size: int = 2048
    # Precompute centrality in a background thread after each read-model build.
    warm_analytics: bool = True

    # Agent / LLM. The key is read by the Anthropic SDK from ANTHROPIC_API_KEY.
    agent_llm_enabled: bool = True
    agent_model: str = "claude-opus-5-5"
    agent_effort: str = "medium"
    agent_max_steps: int = 8
    agent_rate_limit_per_minute: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
