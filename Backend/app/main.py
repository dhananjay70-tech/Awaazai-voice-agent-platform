"""Application factory. Run with: uvicorn app.main:app --reload"""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes import health
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.security_headers import apply_security_headers
from app.db.session import Database
from app.services.rate_limiter import RateLimiter
from app.services.voice_agent_client import VoiceAgentClient

logger = logging.getLogger("app.request")


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    voice_agent_client: VoiceAgentClient | None = None,
) -> FastAPI:
    """Build the app. The optional arguments let tests inject their own dependencies."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("Starting %s (%s)", settings.app_name, settings.environment)
        if settings.jwt_secret is None:
            logger.warning("JWT_SECRET is not set: register/login will return 503 until it is configured")
        if not app.state.database.configured:
            logger.warning("No database configured: database-backed endpoints will return 503")
        yield
        await app.state.voice_agent_client.aclose()
        app.state.database.dispose()
        logger.info("Shutdown complete")

    # Interactive docs and the OpenAPI schema describe every endpoint: only expose them outside production.
    docs_enabled = not settings.is_production
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.state.database = database or Database(
        settings.sqlalchemy_database_url,
        settings.db_connect_timeout_seconds,
        settings.db_pool_size,
        settings.db_max_overflow,
    )
    app.state.rate_limiter = RateLimiter(app.state.database, settings)
    app.state.voice_agent_client = voice_agent_client or VoiceAgentClient(
        settings.voice_agent_base_url, settings.voice_agent_timeout_seconds
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,  # auth uses the Authorization header, not cookies
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Always generate the id server-side: a client-supplied one could inject fake log lines.
        request.state.request_id = uuid.uuid4().hex[:16]
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "%s %s -> %d (%.1f ms) [%s]",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request.state.request_id,
        )
        apply_security_headers(response, request, settings)
        return response

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
