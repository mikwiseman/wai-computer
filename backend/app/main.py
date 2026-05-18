"""FastAPI application entry point."""

import logging
from contextlib import AsyncExitStack, asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Route

from app.api.routes import (
    action_items,
    auth,
    companion,
    dictation,
    entities,
    folders,
    mcp_oauth,
    realtime_transcription,
    realtime_voice,
    recordings,
    search,
)
from app.api.routes import settings as settings_routes
from app.config import get_settings
from app.core.observability import (
    begin_request_context,
    configure_logging,
    end_request_context,
    initialize_sentry,
)
from app.mcp_server import create_mcp_app

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s [%(levelname)s] %(name)s "
        "[request_id=%(request_id)s user_id=%(user_id)s recording_id=%(recording_id)s] "
        "%(message)s"
    ),
)
configure_logging()
logger = logging.getLogger(__name__)

app_settings = get_settings()
mcp_asgi_app = create_mcp_app(app_settings)
initialize_sentry(
    dsn=app_settings.sentry_dsn,
    debug=app_settings.debug,
    include_fastapi=True,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Validate service keys at startup
    if app_settings.realtime_voice_provider == "elevenlabs" and not app_settings.elevenlabs_api_key:
        logger.warning(
            "ELEVENLABS_API_KEY is not configured — realtime voice sessions will not work"
        )
    if app_settings.speech_to_text_provider == "elevenlabs" and not app_settings.elevenlabs_api_key:
        logger.warning(
            "speech_to_text_provider is elevenlabs but ELEVENLABS_API_KEY is not configured"
        )
    if not app_settings.openai_api_key:
        logger.warning(
            "OPENAI_API_KEY is not configured — OpenAI transcription settings will not work"
        )
    if app_settings.realtime_voice_provider != "elevenlabs":
        logger.warning(
            "realtime_voice_provider=%s is unsupported — only elevenlabs is supported",
            app_settings.realtime_voice_provider,
        )
    if app_settings.speech_to_text_provider != "elevenlabs":
        logger.warning(
            "speech_to_text_provider=%s is unsupported — only elevenlabs is supported",
            app_settings.speech_to_text_provider,
        )
    if not app_settings.openai_api_key:
        logger.warning(
            "OPENAI_API_KEY is not configured — Companion, summarization, dictation "
            "cleanup, and embeddings will not work"
        )
    if not app_settings.resend_api_key:
        logger.warning("RESEND_API_KEY is not configured — magic link emails will not work")
    if not app_settings.redis_url:
        logger.warning("REDIS_URL is not configured — agent scheduling will not work")
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(mcp_asgi_app.router.lifespan_context(mcp_asgi_app))

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


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Attach request ids and lifecycle logging to every HTTP request."""
    request_id = request.headers.get("x-request-id") or uuid4().hex
    context_tokens = begin_request_context(
        request_id=request_id,
        request_method=request.method,
        request_path=request.url.path,
    )
    request.state.request_id = request_id
    started_at = perf_counter()

    logger.info("request started")
    response = None
    try:
        response = await call_next(request)
        return response
    except Exception:
        logger.exception("request failed")
        raise
    finally:
        duration_ms = round((perf_counter() - started_at) * 1000, 2)
        status_code = response.status_code if response is not None else 500
        if response is not None:
            response.headers["X-Request-ID"] = request_id
        logger.info("request completed status=%s duration_ms=%s", status_code, duration_ms)
        end_request_context(context_tokens)

# CORS middleware - use configured origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Mcp-Protocol-Version"],
)

# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(recordings.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(settings_routes.router, prefix="/api")
app.include_router(action_items.router, prefix="/api")
app.include_router(entities.router, prefix="/api")
app.include_router(folders.router, prefix="/api")
app.include_router(mcp_oauth.router, prefix="/api")
app.include_router(companion.router, prefix="/api")
app.include_router(dictation.router, prefix="/api")
app.include_router(realtime_transcription.router, prefix="/api")
app.include_router(realtime_voice.router, prefix="/api")


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


for mcp_route in mcp_asgi_app.routes:
    if isinstance(mcp_route, Route):
        app.router.routes.append(
            Route(
                mcp_route.path,
                endpoint=mcp_asgi_app,
                methods=mcp_route.methods,
                include_in_schema=False,
                name=f"mcp:{mcp_route.name}",
            )
        )
