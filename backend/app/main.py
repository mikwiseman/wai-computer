"""FastAPI application entry point."""

import logging
import subprocess
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    action_items,
    auth,
    chat,
    deepgram,
    dictation,
    entities,
    folders,
    recordings,
    search,
)
from app.api.routes import settings as settings_routes
from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app_settings = get_settings()


def _get_release_version() -> str | None:
    """Derive a release version from the git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return f"waicomputer@{result.stdout.strip()}"
    except Exception:
        pass
    return None


if app_settings.sentry_dsn:
    sentry_sdk.init(
        dsn=app_settings.sentry_dsn,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        environment="production" if not app_settings.debug else "development",
        release=_get_release_version(),
        send_default_pii=False,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Validate service keys at startup
    if not app_settings.deepgram_api_key:
        logger.warning("DEEPGRAM_API_KEY is not configured — transcription will not work")
    if not app_settings.anthropic_api_key:
        logger.warning(
            "ANTHROPIC_API_KEY is not configured — summarization and dictation cleanup "
            "will not work"
        )
    if not app_settings.resend_api_key:
        logger.warning("RESEND_API_KEY is not configured — magic link emails will not work")
    if (
        not app_settings.s3_endpoint
        or not app_settings.s3_access_key
        or not app_settings.s3_secret_key
    ):
        logger.warning("S3 credentials are not fully configured — audio storage will not work")

    # Startup: pre-load sentence-transformers model
    logger.info("Pre-loading sentence-transformers embedding model...")
    from app.core.embeddings import get_embedding_generator

    generator = get_embedding_generator()
    generator._load_model()
    logger.info("Embedding model loaded successfully.")

    yield
    # Shutdown
    logger.info("Application shutting down.")


app = FastAPI(
    title=app_settings.app_name,
    description="AI Second Brain - Audio Recording, Transcription, and Organization",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware - use configured origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(recordings.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(settings_routes.router, prefix="/api")
app.include_router(action_items.router, prefix="/api")
app.include_router(entities.router, prefix="/api")
app.include_router(folders.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(deepgram.router, prefix="/api")
app.include_router(dictation.router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "WaiComputer API", "version": "0.1.0"}


@app.get("/health")
async def health():
    """Health check endpoint with database connectivity verification."""
    from sqlalchemy import text

    from app.db.session import async_session_maker

    async with async_session_maker() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "healthy", "database": "connected"}
