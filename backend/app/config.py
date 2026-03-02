"""Application configuration using pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "WaiComputer"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/waicomputer"

    # Auth - JWT_SECRET is REQUIRED, no default for security
    jwt_secret: str  # Must be set via environment variable
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080  # 7 days
    auth_cookie_name: str = "wai_access_token"
    auth_cookie_secure: bool = True
    auth_cookie_samesite: str = "lax"

    # CORS - Configure allowed origins
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:8080",
        "https://wai.computer",
    ]

    # Deepgram
    deepgram_api_key: str = ""

    # Claude/Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # S3 (Hetzner Object Storage)
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "wai-computer"
    s3_region: str = "eu-central"

    # Email (Resend)
    resend_api_key: str = ""
    email_from: str = "WaiComputer <noreply@mail.waiwai.is>"

    # URLs
    frontend_url: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
