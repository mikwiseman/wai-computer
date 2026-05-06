"""Application configuration using pydantic-settings."""

from functools import lru_cache
from ipaddress import ip_address
from tempfile import gettempdir
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "WaiSay"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/waisay"

    # Auth - JWT_SECRET is REQUIRED, no default for security
    jwt_secret: str  # Must be set via environment variable
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    jwt_access_expire_minutes: int = 30  # short-lived access tokens
    jwt_refresh_expire_days: int = 180  # long-lived refresh tokens
    auth_cookie_name: str = "wai_access_token"
    auth_refresh_cookie_name: str = "wai_refresh_token"
    auth_cookie_secure: bool | None = None
    auth_cookie_domain: str | None = None
    auth_cookie_samesite: str = "lax"

    # CORS - Configure allowed origins
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:8080",
        "https://say.waiwai.is",
    ]

    # Voice providers
    # Recording flow uses ElevenLabs Scribe v2 (until Phase 7).
    # Dictation flow uses Inworld with `soniox/stt-rt-v4` — best-in-class
    # Russian recognition (human-parity per Soniox v4 multilingual benchmarks).
    speech_to_text_provider: str = "elevenlabs"
    realtime_voice_provider: str = "elevenlabs"
    dictation_stt_provider: str = "inworld"
    dictation_stt_model: str = "soniox/stt-rt-v4"
    dictation_stt_language: str = "multi"

    # Inworld AI (provides unified STT WebSocket to multiple engines)
    inworld_api_key: str = ""

    # ElevenLabs
    elevenlabs_api_key: str = ""
    elevenlabs_conversation_agent_id: str = ""
    elevenlabs_recording_agent_id: str = ""
    elevenlabs_speech_to_text_model: str = "scribe_v2"
    elevenlabs_realtime_speech_to_text_model: str = "scribe_v2_realtime"
    elevenlabs_no_verbatim: bool = True
    elevenlabs_environment: str = "production"

    # Claude/Anthropic
    anthropic_api_key: str = ""
    # Production default — Sonnet 4.6 (Feb 2026). The previous default,
    # `claude-sonnet-4-20250514`, retires June 15, 2026.
    anthropic_model: str = "claude-sonnet-4-6"
    # Latency-optimised model for dictation cleanup. Sonnet is overkill for
    # filler-word removal + light grammar fixes, and adds 600-1500ms of paste
    # latency; Haiku gives the same quality on this task in a fraction of the time.
    anthropic_dictation_model: str = "claude-haiku-4-5"

    upload_max_bytes: int = 200 * 1024 * 1024
    upload_staging_dir: str = f"{gettempdir()}/waisay/uploads"

    # Email (Resend)
    resend_api_key: str = ""
    email_from: str = "WaiSay <noreply@mail.waiwai.is>"

    # Sentry
    sentry_dsn: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # URLs
    frontend_url: str = "http://localhost:3000"

    # MCP remote connector OAuth
    mcp_issuer_url: str | None = None
    mcp_resource_url: str | None = None
    mcp_access_token_expire_minutes: int = 60
    mcp_refresh_token_expire_days: int = 90
    mcp_authorization_request_expire_minutes: int = 10
    mcp_authorization_code_expire_minutes: int = 10
    mcp_client_secret_expire_days: int = 90
    mcp_max_search_results: int = 20
    mcp_max_tool_text_chars: int = 12000

    @property
    def auth_cookie_secure_resolved(self) -> bool:
        """Use secure cookies on HTTPS frontends unless explicitly overridden."""
        if self.auth_cookie_secure is not None:
            return self.auth_cookie_secure
        return self.frontend_url.startswith("https://")

    @property
    def auth_cookie_domain_resolved(self) -> str | None:
        """Share auth cookies across the app/API subdomains when possible."""
        if self.auth_cookie_domain:
            return self.auth_cookie_domain

        hostname = urlparse(self.frontend_url).hostname
        if not hostname:
            return None

        try:
            ip_address(hostname)
            return None
        except ValueError:
            pass

        if hostname in {"localhost"}:
            return None

        parts = hostname.split(".")
        if len(parts) < 2:
            return None

        # Basic public-suffix heuristic that keeps example.co.uk intact while
        # still collapsing app.example.com -> example.com.
        if len(parts) >= 3 and len(parts[-1]) == 2 and len(parts[-2]) <= 3:
            return ".".join(parts[-3:])

        return ".".join(parts[-2:])

    @property
    def mcp_issuer_url_resolved(self) -> str:
        """Canonical OAuth issuer URL advertised to MCP clients."""
        return (self.mcp_issuer_url or self.frontend_url).rstrip("/")

    @property
    def mcp_resource_url_resolved(self) -> str:
        """Canonical MCP resource URL used for OAuth resource indicators."""
        return (self.mcp_resource_url or f"{self.frontend_url.rstrip('/')}/mcp").rstrip("/")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
