"""Structured errors. Every failure becomes the same JSON shape (the same one the Backend uses):

    {"error": {"code": "...", "message": "...", "details": ..., "request_id": "..."}}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.security_headers import apply_security_headers

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors that should become a clean API response."""

    status_code = 500
    code = "internal_error"
    message = "Internal server error"

    def __init__(self, message: str | None = None, details: Any = None) -> None:
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)


class LLMNotConfiguredError(AppError):
    status_code = 503
    code = "llm_not_configured"
    message = "The AI provider is not configured. Set GEMINI_API_KEY in VoiceAgent/.env and restart the service."


class LLMAuthError(AppError):
    status_code = 502
    code = "llm_authentication_failed"
    message = "The AI provider rejected this service's credentials."


class LLMRateLimitError(AppError):
    status_code = 429
    code = "llm_rate_limited"
    message = "The AI provider quota or rate limit was reached. Please try again later."


class LLMTimeoutError(AppError):
    status_code = 504
    code = "llm_timeout"
    message = "The AI provider did not respond in time."


class LLMUnavailableError(AppError):
    status_code = 503
    code = "llm_unavailable"
    message = "The AI provider is currently unreachable."


class LLMBadResponseError(AppError):
    status_code = 502
    code = "llm_bad_response"
    message = "The AI provider returned an empty or unusable response."


class LLMModelUnavailableError(AppError):
    status_code = 502
    code = "llm_model_unavailable"
    message = (
        "The configured Gemini model is not available to this account. "
        "Set GEMINI_MODEL in VoiceAgent/.env to a supported model and restart the service."
    )


class LLMProviderError(AppError):
    status_code = 502
    code = "llm_provider_error"
    message = "The AI provider failed to process the request."


class GenerationCapacityError(AppError):
    status_code = 503
    code = "generation_capacity_reached"
    message = "The AI service is busy with other conversations. Please retry shortly."


class SttError(AppError):
    """Base for speech-to-text errors. `close_code` is the WebSocket close code used after sending the error event."""

    status_code = 502
    close_code = 1011  # internal / upstream failure


class SttNotConfiguredError(SttError):
    status_code = 503
    code = "stt_not_configured"
    message = "Speech-to-text is not configured. Set DEEPGRAM_API_KEY in VoiceAgent/.env and restart the service."


class SttAuthError(SttError):
    code = "stt_authentication_failed"
    message = "The speech-to-text provider rejected this service's credentials."


class SttRateLimitError(SttError):
    status_code = 429
    code = "stt_rate_limited"
    message = "The speech-to-text provider's quota or concurrency limit was reached. Please try again later."


class SttUnavailableError(SttError):
    status_code = 503
    code = "stt_unavailable"
    message = "The speech-to-text provider is currently unreachable."


class SttProviderError(SttError):
    code = "stt_provider_error"
    message = "The speech-to-text provider failed to process the audio."


class SttBadResponseError(SttError):
    code = "stt_bad_response"
    message = "The speech-to-text provider sent an unusable response."


class SttTimeoutError(SttError):
    status_code = 504
    code = "stt_timeout"
    message = "The speech-to-text provider did not respond in time."


class SttCapacityError(SttError):
    status_code = 503
    code = "stt_capacity_reached"
    message = "Too many transcription streams are active right now. Please retry shortly."
    close_code = 1013  # "try again later"


class SttInvalidConfigError(SttError):
    status_code = 422
    code = "stt_invalid_config"
    message = "The stream configuration is invalid."
    close_code = 1008  # policy violation


class SttInvalidAudioError(SttError):
    status_code = 422
    code = "stt_invalid_audio"
    message = "The audio data is invalid."
    close_code = 1008


class SttLimitExceededError(SttError):
    status_code = 413
    code = "stt_limit_exceeded"
    message = "A stream limit was exceeded."
    close_code = 1009  # too big


class SttIdleTimeoutError(SttError):
    status_code = 408
    code = "stt_idle_timeout"
    message = "No audio was received for too long."
    close_code = 1008


class SttStreamTimeoutError(SttError):
    status_code = 408
    code = "stt_stream_timeout"
    message = "The maximum stream duration was reached."
    close_code = 1008


class TtsNotConfiguredError(AppError):
    status_code = 503
    code = "tts_not_configured"
    message = (
        "Text-to-speech is not configured. Set the API key of the configured TTS_PROVIDER "
        "(DEEPGRAM_API_KEY or SARVAM_API_KEY) in VoiceAgent/.env and restart the service."
    )


class TtsAuthError(AppError):
    status_code = 502
    code = "tts_authentication_failed"
    message = "The text-to-speech provider rejected this service's credentials."


class TtsRateLimitError(AppError):
    status_code = 429
    code = "tts_rate_limited"
    message = "The text-to-speech provider's quota or rate limit was reached. Please try again later."


class TtsTimeoutError(AppError):
    status_code = 504
    code = "tts_timeout"
    message = "The text-to-speech provider did not respond in time."


class TtsUnavailableError(AppError):
    status_code = 503
    code = "tts_unavailable"
    message = "The text-to-speech provider is currently unreachable."


class TtsBadResponseError(AppError):
    status_code = 502
    code = "tts_bad_response"
    message = "The text-to-speech provider returned empty or unusable audio."


class TtsProviderError(AppError):
    status_code = 502
    code = "tts_provider_error"
    message = "The text-to-speech provider failed to process the request."


class TtsCapacityError(AppError):
    status_code = 503
    code = "tts_capacity_reached"
    message = "Too many speech requests are active right now. Please retry shortly."


class TtsInvalidVoiceError(AppError):
    status_code = 422
    code = "tts_invalid_voice"
    message = "The requested voice is not available."


class TtsTextTooLongError(AppError):
    status_code = 422
    code = "tts_text_too_long"
    message = "The text is longer than the configured maximum for speech synthesis."


class SessionBusyError(AppError):
    status_code = 409
    code = "session_busy"
    message = "This session is still processing a previous message. Please retry shortly."


class SessionLimitError(AppError):
    status_code = 503
    code = "session_capacity_reached"
    message = "Too many active conversations right now. Please retry shortly."


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": getattr(request.state, "request_id", None),
    }
    if details is not None:
        body["details"] = details
    return JSONResponse({"error": body}, status_code=status_code, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations and messages only: submitted values (which may be user speech/text) are not echoed.
        details = [
            {"field": ".".join(str(part) for part in err["loc"] if part != "body"), "message": err["msg"]}
            for err in exc.errors()
        ]
        return error_response(request, 422, "validation_error", "Request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(request, exc.status_code, f"http_{exc.status_code}", str(exc.detail), headers=exc.headers)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Starlette answers unhandled errors outside our middleware, so request id/headers are added here.
        logger.exception(
            "Unhandled error on %s %s [%s]", request.method, request.url.path, getattr(request.state, "request_id", None)
        )
        response = error_response(request, 500, "internal_error", "Internal server error")
        apply_security_headers(response, request)
        return response
