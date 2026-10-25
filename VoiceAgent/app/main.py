"""Application factory. Run with: uvicorn app.main:app --port 8001"""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.chat_service import ChatService
from app.config import Settings, get_settings
from app.errors import register_exception_handlers
from app.llm.base import LLMProvider
from app.llm.gemini import GeminiProvider
from app.logging_setup import configure_logging
from app.routes import chat, health, stt, tts, voice
from app.security_headers import apply_security_headers
from app.sessions import SessionStore
from app.stt.base import STTProvider
from app.stt.deepgram import DeepgramProvider
from app.stt.service import SttStreamService
from app.tts.base import TTSProvider
from app.tts.deepgram import DeepgramTtsProvider
from app.tts.sarvam import SarvamTtsProvider
from app.tts.service import TtsService
from app.voice.service import VoiceStreamService

logger = logging.getLogger("app.request")


def build_provider(settings: Settings) -> LLMProvider | None:
    """The configured LLM provider, or None when no API key is set (the service still starts)."""
    if settings.gemini_api_key is None:
        return None
    return GeminiProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_model,
        timeout_seconds=settings.llm_timeout_seconds,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
    )


def build_stt_provider(settings: Settings) -> STTProvider | None:
    """The configured speech-to-text provider, or None when no API key is set (the service still starts)."""
    if settings.deepgram_api_key is None:
        return None
    return DeepgramProvider(
        api_key=settings.deepgram_api_key.get_secret_value(),
        model=settings.deepgram_model,
        url=settings.deepgram_url,
        language_codes={
            "english": settings.deepgram_language_english,
            "hindi": settings.deepgram_language_hindi,
            "hinglish": settings.deepgram_language_hinglish,
        },
        endpointing_ms=settings.deepgram_endpointing_ms,
        endpointing_ms_by_language={"hinglish": settings.deepgram_endpointing_ms_hinglish},
        connect_timeout_seconds=settings.stt_connect_timeout_seconds,
    )


def build_tts_provider(settings: Settings) -> TTSProvider | None:
    """The text-to-speech provider chosen by TTS_PROVIDER, or None when that provider's API key is not set."""
    if settings.tts_provider == "sarvam":
        if settings.sarvam_api_key is None:
            return None
        return SarvamTtsProvider(
            api_key=settings.sarvam_api_key.get_secret_value(),
            url=settings.sarvam_tts_url,
            model=settings.sarvam_tts_model,
            language_codes=settings.sarvam_language_codes,
            default_speakers=settings.sarvam_default_speakers,
            sample_rate=settings.sarvam_tts_sample_rate,
            bitrate=settings.sarvam_tts_bitrate,
            timeout_seconds=settings.tts_timeout_seconds,
            max_connections=settings.tts_max_concurrent_requests,
        )
    if settings.deepgram_api_key is None:
        return None
    return DeepgramTtsProvider(
        api_key=settings.deepgram_api_key.get_secret_value(),
        default_voice=settings.deepgram_tts_model,
        url=settings.deepgram_tts_url,
        bit_rate=settings.deepgram_tts_bit_rate,
        timeout_seconds=settings.tts_timeout_seconds,
        max_connections=settings.tts_max_concurrent_requests,
    )


def create_app(
    settings: Settings | None = None,
    llm_provider: LLMProvider | None = None,
    session_store: SessionStore | None = None,
    stt_provider: STTProvider | None = None,
    tts_provider: TTSProvider | None = None,
) -> FastAPI:
    """Build the app. The optional arguments let tests inject their own settings, providers and session store."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    provider = llm_provider if llm_provider is not None else build_provider(settings)
    store = session_store or SessionStore(
        max_sessions=settings.session_max_sessions,
        ttl_seconds=settings.session_ttl_seconds,
        max_turns=settings.session_max_turns,
        max_history_chars=settings.session_max_history_chars,
    )
    chat_service = ChatService(provider, store, settings)
    stt_service = SttStreamService(stt_provider if stt_provider is not None else build_stt_provider(settings), settings)
    tts_service = TtsService(tts_provider if tts_provider is not None else build_tts_provider(settings), settings)
    voice_service = VoiceStreamService(settings, stt_service, chat_service, tts_service)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if provider is None:
            logger.warning("GEMINI_API_KEY is not set: /chat will return 503 until it is configured")
        if not stt_service.configured:
            logger.warning("DEEPGRAM_API_KEY is not set: /stt/stream will report stt_not_configured until it is configured")
        if not tts_service.configured:
            key_name = "SARVAM_API_KEY" if settings.tts_provider == "sarvam" else "DEEPGRAM_API_KEY"
            logger.warning("%s is not set: /tts/stream (TTS_PROVIDER=%s) will report tts_not_configured", key_name, settings.tts_provider)
        yield
        await chat_service.aclose()
        await tts_service.aclose()

    # Interactive docs describe every endpoint: only expose them outside production.
    docs_enabled = not settings.is_production
    app = FastAPI(
        title=settings.service_name,
        version=settings.service_version,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.chat_service = chat_service
    app.state.stt_service = stt_service
    app.state.tts_service = tts_service
    app.state.voice_service = voice_service

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
        apply_security_headers(response, request, serves_docs=docs_enabled)
        return response

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(stt.router)
    app.include_router(tts.router)
    app.include_router(voice.router)
    return app


app = create_app()
