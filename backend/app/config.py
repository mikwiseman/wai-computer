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
    app_name: str = "WaiComputer"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/waicomputer"

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
        "https://wai.computer",
    ]

    # Voice provider
    realtime_voice_provider: str = "elevenlabs"

    # OpenAI — LLM (Companion + summarization + dictation cleanup) and embeddings.
    openai_api_key: str = ""
    openai_llm_model: str = "gpt-5.5"
    openai_embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 1536

    # Inworld AI (first-party STT experiments; realtime only)
    inworld_api_key: str = ""
    inworld_workspace: str = ""

    # ElevenLabs
    elevenlabs_api_key: str = ""
    elevenlabs_conversation_agent_id: str = ""
    elevenlabs_recording_agent_id: str = ""
    elevenlabs_speech_to_text_model: str = "scribe_v2"
    elevenlabs_realtime_speech_to_text_model: str = "scribe_v2_realtime"
    elevenlabs_no_verbatim: bool = True
    elevenlabs_environment: str = "production"

    # Deepgram (batch STT + server-proxied realtime; API key stays backend-only)
    deepgram_api_key: str = ""
    deepgram_file_stt_model: str = "nova-3"
    deepgram_realtime_proxy_token_ttl_seconds: int = 10 * 60

    # Soniox (direct realtime + async batch)
    soniox_api_key: str = ""
    soniox_realtime_stt_model: str = "stt-rt-v4"
    soniox_file_stt_model: str = "stt-async-v4"

    upload_max_bytes: int = 200 * 1024 * 1024
    upload_staging_dir: str = f"{gettempdir()}/waicomputer/uploads"
    # Optional speaker-to-person matching is CPU/RAM heavy because it loads a
    # SpeechBrain ECAPA model. Keep it off on the main API path until it runs
    # in an isolated worker with enough memory.
    voice_identification_enabled: bool = False
    recording_processing_stale_after_minutes: int = 15

    # Telegram bot integration. Token and webhook secret are backend-only.
    telegram_bot_token: str = ""
    telegram_bot_username: str = "waicomputer_bot"
    telegram_webhook_secret_token: str = ""
    # Telegram Bot API file downloads are limited to 20 MB.
    telegram_download_max_bytes: int = 20 * 1024 * 1024

    # Email (Resend)
    resend_api_key: str = ""
    email_from: str = "WaiComputer <noreply@mail.waiwai.is>"

    # Sentry
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1
    sentry_profiles_sample_rate: float = 0.1

    # Observability
    log_format: str = "json"
    recording_monitoring_min_coverage_ratio: float = 0.8
    recording_monitoring_failure_rate_critical: float = 0.2
    recording_monitoring_min_volume_24h: int = 3

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # URLs
    frontend_url: str = "http://localhost:3000"

    # Billing — Stripe (global rail)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""
    # Enable once a head-office address is configured in Stripe Tax settings.
    stripe_automatic_tax: bool = False

    # Billing — T-Bank acquiring (RU rail)
    tinkoff_api_url: str = "https://securepay.tinkoff.ru/v2/"
    tinkoff_terminal_key: str = ""
    tinkoff_password: str = ""

    # Billing — generic
    billing_trial_days: int = 0
    billing_refund_window_days: int = 7
    billing_default_region: str = "global"
    admin_password: str = ""
    # Master switch. When false (the default) the backend ignores word caps
    # entirely and /api/billing/subscription advertises enforcement_enabled
    # so clients can hide every billing UI surface. Flip to true at the
    # moment we commit to paid SKUs.
    billing_enforcement_enabled: bool = False

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
