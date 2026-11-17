"""Process configuration, read from environment variables prefixed ``SONGNEXUS_``.

Paths never depend on where the package is installed (a v0 bug): the data
directory is configured explicitly, or discovered from the working directory.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from songnexus.catalog.sources import GENRE_SOURCE_IDS


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

    # Response cache (performance). Empty: in-process only. A URL such as
    # redis://10.0.0.3:6379/0 shares cached catalog responses between instances.
    redis_url: str = ""

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
    # Wikimedia asks for an identifying User-Agent; the contact is optional here too.
    wikidata_sparql_url: str = "https://query.wikidata.org/sparql"
    wikidata_contact: str = ""
    discogs_dumps_url: str = "https://data.discogs.com/"
    acousticbrainz_base_url: str = "https://acousticbrainz.org/api/v1"
    listenbrainz_api_url: str = "https://api.listenbrainz.org"
    listenbrainz_labs_url: str = "https://labs.api.listenbrainz.org"

    # Linked listening accounts (ADR 0006). Tokens are encrypted with these keys
    # ({"key id": "base64 32-byte key"}); generate one with `songnexus new-token-key`.
    # Without keys, no provider is offered. A provider is offered only when its own
    # keys are set too (ListenBrainz needs none).
    token_keys: dict[str, str] = Field(default_factory=dict)
    token_key_id: str = ""
    # Where the browser app is served; OAuth callbacks come back through its /v1 proxy.
    app_origin: str = "http://127.0.0.1:5173"
    spotify_client_id: str = ""
    # Google OAuth client (web application) with the YouTube Data API enabled: links
    # YouTube Music through liked songs. Without it, YouTube Music is file import only.
    google_client_id: str = ""
    google_client_secret: str = ""
    deezer_app_id: str = ""
    deezer_secret: str = ""
    lastfm_api_key: str = ""
    lastfm_secret: str = ""
    librefm_api_key: str = ""
    librefm_secret: str = ""
    apple_music_developer_token: str = ""
    lastfm_api_url: str = "https://ws.audioscrobbler.com/2.0/"
    librefm_api_url: str = "https://libre.fm/2.0/"
    sync_interval_minutes: int = 15
    # Run the sync job inside the API process (one instance only: local development).
    # Deployed environments schedule `songnexus sync-accounts` instead.
    sync_in_process: bool = False

    # Around you (community charts). A chart is recomputed when older than this,
    # on read or by `songnexus community-charts`; leaving or joining shows up at the
    # next recompute, which also keeps one person's change from being singled out.
    community_chart_ttl_minutes: int = 60

    # Ask (AI in the search bar, ADR 0008). The model only interprets questions; answers
    # come from the catalog. Providers: gemini (default), openrouter, ollama; "none" or a
    # hosted provider without a key means the built-in parser alone. Only the question
    # text is sent. The model defaults per provider (core/ask/llm.py DEFAULT_MODELS).
    llm_provider: str = "gemini"
    llm_api_key: str = Field(default="", repr=False)
    llm_model: str = ""
    llm_base_url: str = ""
    llm_timeout_s: float = 4.0

    @property
    def local_token_key_path(self) -> Path:
        """Development only: where a generated token key is kept (git-ignored)."""
        return self.raw_dir("local") / "token-key.json"

    # Which genre sources the read model uses (ADR 0003, ADR 0005). A commercial
    # build sets ["discogs"] to drop the non-commercial MusicBrainz genres.
    genre_sources: list[str] = Field(
        default_factory=lambda: ["musicbrainz-supplementary", "discogs"]
    )

    @field_validator("genre_sources")
    @classmethod
    def _known_genre_sources(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(GENRE_SOURCE_IDS))
        if unknown:
            raise ValueError(f"unknown genre sources {unknown}; choose from {GENRE_SOURCE_IDS}")
        return value

    @property
    def snapshot_path(self) -> Path:
        """The committed catalog snapshot that ingestion reads."""
        return self.data_dir / "samples" / "musicbrainz_snapshot.jsonl.gz"

    @property
    def seeds_path(self) -> Path:
        """The seed-artist list that the fetch pipeline expands."""
        return self.data_dir / "seeds" / "seed_artists.json"

    @property
    def wikidata_snapshot_path(self) -> Path:
        """The committed Wikidata snapshot (artist links to Discogs, genre hierarchy)."""
        return self.data_dir / "samples" / "wikidata_snapshot.jsonl.gz"

    @property
    def discogs_snapshot_path(self) -> Path:
        """The committed extract of the Discogs masters dump for catalog artists."""
        return self.data_dir / "samples" / "discogs_snapshot.jsonl.gz"

    @property
    def acousticbrainz_snapshot_path(self) -> Path:
        """The committed AcousticBrainz descriptors for catalog recordings."""
        return self.data_dir / "samples" / "acousticbrainz_snapshot.jsonl.gz"

    @property
    def listenbrainz_snapshot_path(self) -> Path:
        """The committed ListenBrainz listener counts and co-listening for catalog artists."""
        return self.data_dir / "samples" / "listenbrainz_snapshot.jsonl.gz"

    @property
    def genre_map_path(self) -> Path:
        """The reviewed Discogs-to-MusicBrainz genre table."""
        return self.data_dir / "seeds" / "discogs_genre_map.json"

    @property
    def raw_cache_dir(self) -> Path:
        """Local HTTP cache for the fetch pipeline (git-ignored)."""
        return self.raw_dir("musicbrainz")

    def raw_dir(self, source: str) -> Path:
        """Local, git-ignored cache for one source's downloads."""
        return self.data_dir / "raw" / source


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
