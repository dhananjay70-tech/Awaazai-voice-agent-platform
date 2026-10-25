"""POST /tts/stream use case: validate, take a concurrency slot, stream audio from the provider.

Everything that can fail before audio exists (not configured, bad voice, text too long, no free slot, provider
rejected the request) raises before the first yield, so it becomes a JSON error with a real HTTP status. Audio is
passed through chunk by chunk: nothing is accumulated, and the upstream connection and the slot are released in
`finally` however the stream ends. Text and audio are never logged, only lengths and timings.
"""

import asyncio
import logging
import time
import traceback
from collections.abc import AsyncIterator, Callable

from app.config import Settings
from app.errors import (
    AppError,
    TtsBadResponseError,
    TtsCapacityError,
    TtsInvalidVoiceError,
    TtsNotConfiguredError,
    TtsTextTooLongError,
    TtsTimeoutError,
)
from app.limits import GenerationLimiter
from app.tts.base import TTSProvider

logger = logging.getLogger(__name__)

DEFAULT_VOICE_NAME = "default"


class TtsService:
    def __init__(
        self,
        provider: TTSProvider | None,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._provider = provider  # None when the configured provider has no API key
        self._clock = clock
        self._s = settings
        self.limiter = GenerationLimiter(
            settings.tts_max_concurrent_requests, settings.tts_queue_timeout_seconds, TtsCapacityError
        )

    @property
    def configured(self) -> bool:
        return self._provider is not None

    @property
    def content_type(self) -> str:
        assert self._provider is not None
        return self._provider.content_type

    @property
    def send_timeout(self) -> float:
        return self._s.tts_send_timeout_seconds

    async def aclose(self) -> None:
        aclose = getattr(self._provider, "aclose", None)
        if aclose is not None:
            await aclose()

    def prepare(self, *, text: str, language: str, voice: str | None) -> AsyncIterator[bytes]:
        """Validate eagerly (so errors are plain JSON responses) and return the not-yet-started audio generator."""
        if self._provider is None:
            raise TtsNotConfiguredError()
        if len(text) > self._s.tts_max_text_chars:
            raise TtsTextTooLongError(f"The text may be at most {self._s.tts_max_text_chars} characters.")
        if voice is None or voice == DEFAULT_VOICE_NAME:
            voice = self._provider.default_voice_for(language)
        elif voice not in self._s.tts_allowed_voices:
            raise TtsInvalidVoiceError()
        return self._stream(self._provider, text, language, voice)

    async def _stream(self, provider: TTSProvider, text: str, language: str, voice: str) -> AsyncIterator[bytes]:
        started = self._clock()
        audio_bytes = chunks = 0
        first_audio_ms: float | None = None
        outcome, error_code = "cancelled", None  # stays "cancelled" if we are closed or cancelled mid-stream
        upstream: AsyncIterator[bytes] | None = None
        try:
            async with self.limiter.slot():
                upstream = provider.stream(text=text, voice=voice, language=language)
                while True:
                    remaining = self._s.tts_stream_timeout_seconds - (self._clock() - started)
                    try:
                        async with asyncio.timeout(max(0.0, min(remaining, self._s.tts_timeout_seconds))):
                            chunk = await anext(upstream)
                    except StopAsyncIteration:
                        break
                    except TimeoutError:
                        raise TtsTimeoutError() from None
                    if not chunk:
                        continue
                    if first_audio_ms is None:
                        first_audio_ms = (self._clock() - started) * 1000
                    audio_bytes += len(chunk)
                    chunks += 1
                    yield chunk
                if audio_bytes == 0:
                    raise TtsBadResponseError()
            outcome = "completed"
        except AppError as exc:
            outcome = "timeout" if isinstance(exc, TtsTimeoutError) else "failed"
            error_code = exc.code
            raise
        except Exception as exc:
            outcome, error_code = "failed", "internal_error"
            # Type and traceback FRAMES only: the exception message could contain request text.
            logger.error(
                "Unexpected error in TTS stream: %s\n%s", type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__))
            )
            raise AppError() from None
        finally:
            if upstream is not None:
                aclose = getattr(upstream, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()  # close the upstream HTTP connection before the slot is released
                    except Exception:
                        logger.debug("closing the provider audio stream failed", exc_info=False)
            logger.log(
                logging.INFO if outcome in ("completed", "cancelled") else logging.WARNING,
                "tts stream finished: outcome=%s error=%s language=%s voice=%s text_chars=%d audio_bytes=%d chunks=%d "
                "first_audio_ms=%s total_ms=%.0f",
                outcome, error_code or "-", language, voice, len(text), audio_bytes, chunks,
                "-" if first_audio_ms is None else f"{first_audio_ms:.0f}",
                (self._clock() - started) * 1000,
            )
