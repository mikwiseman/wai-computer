"""FastAPI application entry point."""

import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Route

from app.api.routes import (
    action_items,
    admin,
    agents,
    api_keys,
    auth,
    benchmarks,
    brain,
    brain_spaces,
    companion,
    comparisons,
    dictation,
    entities,
    folders,
    inbox,
    items,
    mcp_connect,
    mcp_connections,
    mcp_oauth,
    memory_proposals,
    people,
    personalization,
    realtime_transcription,
    realtime_voice,
    recordings,
    reminders,
    search,
    sentry_webhook,
    source_catalog,
    system,
    telegram,
    voice_enrollment,
    wai,
)
from app.api.routes import devices as devices_routes
from app.api.routes import settings as settings_routes
from app.api.routes import voice as voice_routes
from app.billing.router import router as billing_router
from app.billing.webhooks import router as billing_webhooks_router
from app.config import get_settings
from app.core.observability import (
    begin_request_context,
    configure_logging,
    end_request_context,
    initialize_sentry,
)
from app.core.recording_recovery import mark_stale_processing_recordings
from app.db.session import async_session_maker
from app.mcp_server import create_mcp_app

app_settings = get_settings()
logging.basicConfig(level=logging.INFO)
configure_logging(log_format=app_settings.log_format)
logger = logging.getLogger(__name__)

mcp_asgi_app = create_mcp_app(app_settings)
initialize_sentry(
    dsn=app_settings.sentry_dsn,
    debug=app_settings.debug,
    include_fastapi=True,
    traces_sample_rate=app_settings.sentry_traces_sample_rate,
    profiles_sample_rate=app_settings.sentry_profiles_sample_rate,
)


async def _health_database_metadata(
    session_factory: Callable[[], object],
) -> dict[str, str | None]:
    """Verify DB connectivity and expose the applied Alembic schema revision."""
    from sqlalchemy import text

    async with session_factory() as session:
        execute: Callable[..., Awaitable[object]] = session.execute
        await execute(text("SELECT 1"))
        schema_revision = None
        try:
            result = await execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            scalar = getattr(result, "scalar_one_or_none", None)
            if callable(scalar):
                schema_revision = scalar()
        except Exception:
            logger.warning("database schema revision unavailable", exc_info=True)
        return {"database": "connected", "schema_revision": schema_revision}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Validate service keys at startup
    if app_settings.realtime_voice_provider == "elevenlabs" and not app_settings.elevenlabs_api_key:
        logger.warning(
            "ELEVENLABS_API_KEY is not configured — realtime voice sessions will not work"
        )
    if not app_settings.openai_api_key:
        logger.warning(
            "OPENAI_API_KEY is not configured — Companion, OCR, comparisons, "
            "memory tasks, and embeddings will not work"
        )
    if not app_settings.cerebras_api_key:
        logger.warning(
            "CEREBRAS_API_KEY is not configured — summarization and dictation "
            "cleanup will not work"
        )
    if not app_settings.deepgram_api_key:
        logger.warning("DEEPGRAM_API_KEY is not configured — live transcription will not work")
    if app_settings.realtime_voice_provider != "elevenlabs":
        logger.warning(
            "realtime_voice_provider=%s is unsupported — only elevenlabs is supported",
            app_settings.realtime_voice_provider,
        )
    if not app_settings.resend_api_key:
        logger.warning("RESEND_API_KEY is not configured — magic link emails will not work")
    if not app_settings.redis_url:
        logger.warning("REDIS_URL is not configured — agent scheduling will not work")
    if app_settings.recording_processing_stale_after_minutes > 0:
        async with async_session_maker() as session:
            recovered_count = await mark_stale_processing_recordings(
                session,
                stale_after=timedelta(
                    minutes=app_settings.recording_processing_stale_after_minutes
                ),
            )
        if recovered_count:
            logger.warning(
                "marked stale processing recordings as failed count=%s",
                recovered_count,
            )
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(mcp_asgi_app.router.lifespan_context(mcp_asgi_app))
        yield
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
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Mcp-Protocol-Version",
        "X-Wai-Admin-Password",
    ],
)

# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(api_keys.router, prefix="/api")
app.include_router(benchmarks.router, prefix="/api")
app.include_router(recordings.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(telegram.router, prefix="/api")
app.include_router(reminders.router, prefix="/api")
app.include_router(sentry_webhook.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(system.self_host_router, prefix="/api")
app.include_router(settings_routes.router, prefix="/api")
app.include_router(action_items.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(entities.router, prefix="/api")
app.include_router(folders.router, prefix="/api")
app.include_router(inbox.router, prefix="/api")
app.include_router(items.router, prefix="/api")
app.include_router(comparisons.router, prefix="/api")
app.include_router(mcp_connect.router, prefix="/api")
app.include_router(mcp_connections.router, prefix="/api")
app.include_router(source_catalog.router, prefix="/api")
app.include_router(memory_proposals.router, prefix="/api")
app.include_router(brain_spaces.router, prefix="/api")
app.include_router(brain.router, prefix="/api")
app.include_router(people.router, prefix="/api")
app.include_router(personalization.router, prefix="/api")
app.include_router(voice_enrollment.router, prefix="/api")
app.include_router(mcp_oauth.router, prefix="/api")
app.include_router(companion.router, prefix="/api")
app.include_router(devices_routes.router, prefix="/api")
app.include_router(dictation.router, prefix="/api")
app.include_router(realtime_transcription.router, prefix="/api")
app.include_router(realtime_voice.router, prefix="/api")
app.include_router(voice_routes.router, prefix="/api")
app.include_router(wai.router, prefix="/api")
app.include_router(billing_router, prefix="/api")
app.include_router(billing_webhooks_router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "WaiComputer API", "version": "0.1.0"}


@app.get("/health")
async def health():
    """Health check endpoint with database connectivity verification."""
    from app.db.session import async_session_maker

    database = await _health_database_metadata(async_session_maker)
    return {
        "status": "healthy",
        **database,
        "git_sha": app_settings.git_sha,
        "git_dirty": app_settings.git_dirty,
    }


@app.get("/health/live")
async def health_live():
    """Liveness check that only verifies the process can answer."""
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready():
    """Readiness check for load balancers and external uptime probes."""
    return await health()


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
