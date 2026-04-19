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
    speech_to_text_provider: str = "elevenlabs"
    realtime_voice_provider: str = "elevenlabs"

    # ElevenLabs
    elevenlabs_api_key: str = ""
    elevenlabs_conversation_agent_id: str = ""
    elevenlabs_recording_agent_id: str = ""
    elevenlabs_speech_to_text_model: str = "scribe_v2"
    elevenlabs_realtime_speech_to_text_model: str = "scribe_v2_realtime"
    elevenlabs_environment: str = "production"

    # Claude/Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

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


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
