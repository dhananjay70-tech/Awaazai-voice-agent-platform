"""WS /stt/stream orchestration: validates audio, forwards it to the STT provider, relays transcript events.

Per stream, one handler task supervises two child tasks:
  reader: client -> provider   (config, binary audio frames, "end")
  writer: provider -> client   (partial / final events)
Whatever way the stream ends (done, error, timeout, client disconnect, cancellation of the handler), the children are
cancelled and awaited, the provider connection is closed, and the concurrency slot is released, all in `finally`
blocks. Audio is never accumulated: a frame is read from the client only after the previous one was handed to the
provider (backpressure), and nothing is written to disk. Transcripts and audio are never logged.
"""

import asyncio
import json
import logging
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket
from pydantic import ValidationError

from app.config import Settings
from app.errors import (
    AppError,
    SttCapacityError,
    SttError,
    SttIdleTimeoutError,
    SttInvalidAudioError,
    SttInvalidConfigError,
    SttLimitExceededError,
    SttNotConfiguredError,
    SttProviderError,
    SttStreamTimeoutError,
    SttTimeoutError,
)
from app.limits import GenerationLimiter
from app.stt.base import AudioFormat, STTProvider, STTSession
from app.stt.protocol import (
    MAX_CONTROL_MESSAGE_BYTES,
    SttConfigMessage,
    done_event,
    error_event,
    final_event,
    partial_event,
    ready_event,
)

logger = logging.getLogger(__name__)

# Audio may arrive a little faster than real time (a client flushing buffered audio on connect), but not sustained
# bulk uploads: this endpoint is for live speech, and Deepgram bills and rate-limits by audio duration.
MAX_REALTIME_FACTOR = 2.0
BURST_SECONDS = 10.0
ERROR_SEND_TIMEOUT = 2.0  # best-effort delivery of the final error event


class ClientGone(Exception):
    """The client disconnected or stopped reading."""


@dataclass
class _Stats:
    started: float
    bytes_per_second: int = 32_000  # set from the stream's audio format once the config is known
    language: str = "-"
    audio_bytes: int = 0
    partials: int = 0
    finals: int = 0
    seq: int = 0
    first_partial_ms: float | None = None
    first_final_ms: float | None = None
    last_partial: str | None = None


class SttStreamService:
    def __init__(
        self,
        provider: STTProvider | None,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,  # monotonic, injectable for deterministic timing tests
    ) -> None:
        self._provider = provider  # None when no API key is configured
        self._clock = clock
        self._s = settings
        # Streams are long-lived: when full, fail immediately (the client retries) instead of queueing.
        self.limiter = GenerationLimiter(settings.stt_max_concurrent_streams, 0.0, SttCapacityError)

    @property
    def configured(self) -> bool:
        return self._provider is not None

    @property
    def provider(self) -> STTProvider | None:
        """The configured provider, for services (WS /voice/stream) that compose STT without the socket protocol."""
        return self._provider

    # ------------------------------------------------------------------ entry point

    async def run(self, websocket: WebSocket, request_id: str) -> None:
        if not self._origin_allowed(websocket.headers.get("origin")):
            logger.warning("STT connection rejected: origin not allowed [%s]", request_id)
            await websocket.close(code=1008)  # before accept: the handshake is refused (HTTP 403)
            return

        await websocket.accept(
            headers=[
                (b"x-request-id", request_id.encode()),
                (b"x-content-type-options", b"nosniff"),
                (b"cache-control", b"no-store"),
            ]
        )
        stats = _Stats(started=self._clock())
        stream_id = uuid.uuid4().hex
        outcome, error_code = "cancelled", None  # stays "cancelled" if the handler itself is cancelled
        session: STTSession | None = None
        try:
            if self._provider is None:
                raise SttNotConfiguredError()
            async with self.limiter.slot():
                config = await self._read_config(websocket)
                audio = AudioFormat(config.encoding, config.sample_rate, config.channels)
                stats.language = config.language
                stats.bytes_per_second = audio.bytes_per_second
                session = await self._provider.open(language=config.language, audio=audio)
                await self._send(
                    websocket,
                    ready_event(
                        stream_id=stream_id, request_id=request_id, language=config.language,
                        model=self._provider.model, sample_rate=audio.sample_rate, channels=audio.channels,
                    ),
                )
                await self._pump(websocket, session, audio, stats, request_id)
                await self._send(websocket, done_event(**self._summary(stream_id, stats)))
            outcome = "completed"
            await self._close(websocket, 1000)
        except ClientGone:
            outcome = "cancelled"
        except SttError as exc:
            outcome = "timeout" if isinstance(exc, (SttIdleTimeoutError, SttStreamTimeoutError, SttTimeoutError)) else "failed"
            error_code = exc.code
            await self._fail(websocket, request_id, exc)
        except AppError as exc:
            outcome, error_code = "failed", exc.code
            await self._fail(websocket, request_id, exc)
        except Exception as exc:
            outcome, error_code = "failed", "internal_error"
            # Type and traceback FRAMES only: the exception message could contain audio or transcript text.
            logger.error(
                "Unexpected error in STT stream [%s]: %s\n%s",
                request_id, type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__)),
            )
            await self._fail(websocket, request_id, AppError())
        finally:
            if session is not None:
                await session.aclose()  # closes the provider connection before the slot is released
            self._log_finished(outcome, error_code, stats)
            if outcome == "cancelled":
                await self._close(websocket, 1001)

    # ------------------------------------------------------------------ config handshake

    def _origin_allowed(self, origin: str | None) -> bool:
        if origin is None:
            return True  # not a browser: scripts and the Backend send no Origin header
        allowed = self._s.stt_origin_list
        return "*" in allowed or origin in allowed

    async def _read_config(self, websocket: WebSocket) -> SttConfigMessage:
        message = await self._receive(websocket)
        text = message.get("text")
        if text is None:
            raise SttInvalidConfigError("The first message must be a JSON config message, sent before any audio.")
        if len(text.encode("utf-8")) > MAX_CONTROL_MESSAGE_BYTES:
            raise SttInvalidConfigError("The config message is too large.")
        try:
            return SttConfigMessage.model_validate_json(text)
        except ValidationError as exc:
            # Field names and constraint messages only: submitted values are never echoed back.
            details = [{"field": ".".join(str(p) for p in err["loc"]) or "config", "message": err["msg"]} for err in exc.errors()]
            raise SttInvalidConfigError(details=details) from None

    # ------------------------------------------------------------------ the two directions

    async def _pump(self, websocket: WebSocket, session: STTSession, audio: AudioFormat, stats: _Stats, request_id: str) -> None:
        reader = asyncio.create_task(self._read_client(websocket, session, audio, stats), name="stt-reader")
        writer = asyncio.create_task(self._write_events(websocket, session, stats), name="stt-writer")
        try:
            try:
                async with asyncio.timeout(self._s.stt_max_stream_seconds):
                    done, _ = await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_COMPLETED)
                    if reader not in done:
                        # Only the provider side finished while the client is still sending: it hung up on us.
                        writer.result()  # ...with an error, if it reported one
                        raise SttProviderError("The speech-to-text provider ended the stream unexpectedly.")
                    # The client side finished first (or together with the provider, which is normal after "end").
                    reader.result()  # a client error / disconnect surfaces here; a normal return means "end" was sent
                    try:
                        async with asyncio.timeout(self._s.stt_finish_timeout_seconds):
                            await writer  # the provider flushes its remaining final transcripts
                    except TimeoutError:
                        raise SttTimeoutError("The speech-to-text provider did not finish in time.") from None
            except TimeoutError:
                raise SttStreamTimeoutError() from None
        finally:
            for task in (reader, writer):
                task.cancel()
            await asyncio.gather(reader, writer, return_exceptions=True)  # wait until both are really finished

    async def _read_client(self, websocket: WebSocket, session: STTSession, audio: AudioFormat, stats: _Stats) -> None:
        while True:
            message = await self._receive(websocket)
            chunk = message.get("bytes")
            if chunk is not None:
                self._check_audio(chunk, audio, stats)
                await session.send_audio(chunk)  # backpressure: the next frame is read only after this returns
                continue
            self._check_control(message.get("text"))
            await session.finish()
            return

    async def _write_events(self, websocket: WebSocket, session: STTSession, stats: _Stats) -> None:
        events = session.events()
        try:
            await self._relay(websocket, events, stats)
        finally:
            aclose = getattr(events, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()  # close the provider's event generator now, not whenever the GC gets to it
                except Exception:
                    logger.debug("closing the provider event stream failed", exc_info=False)

    async def _relay(self, websocket: WebSocket, events: Any, stats: _Stats) -> None:
        async for event in events:
            elapsed_ms = (self._clock() - stats.started) * 1000
            if event.kind == "partial":
                if event.text == stats.last_partial:
                    continue  # the same hypothesis again is not news
                stats.last_partial = event.text
                stats.partials += 1
                if stats.first_partial_ms is None:
                    stats.first_partial_ms = elapsed_ms
                stats.seq += 1
                await self._send(websocket, partial_event(stats.seq, event.text))
            else:
                stats.last_partial = None  # a new segment starts: its first partial is new again
                stats.finals += 1
                if stats.first_final_ms is None:
                    stats.first_final_ms = elapsed_ms
                stats.seq += 1
                await self._send(
                    websocket,
                    final_event(stats.seq, event.text, event.start, event.duration, event.speech_final, event.confidence),
                )

    # ------------------------------------------------------------------ validation

    def _check_audio(self, chunk: bytes, audio: AudioFormat, stats: _Stats) -> None:
        if not chunk:
            raise SttInvalidAudioError("Empty audio frame.")
        if len(chunk) > self._s.stt_max_chunk_bytes:
            raise SttLimitExceededError(f"Audio frame larger than {self._s.stt_max_chunk_bytes} bytes.")
        if len(chunk) % audio.frame_bytes:
            raise SttInvalidAudioError("Audio frames must contain whole 16-bit samples.")
        stats.audio_bytes += len(chunk)
        seconds = stats.audio_bytes / audio.bytes_per_second
        if seconds > self._s.stt_max_audio_seconds:
            raise SttLimitExceededError(f"The maximum audio duration of {self._s.stt_max_audio_seconds:g} s was reached.")
        elapsed = self._clock() - stats.started
        if seconds > MAX_REALTIME_FACTOR * elapsed + BURST_SECONDS:
            raise SttLimitExceededError("Audio is being sent much faster than real time.")

    @staticmethod
    def _check_control(text: str | None) -> None:
        if text is None or len(text.encode("utf-8")) > MAX_CONTROL_MESSAGE_BYTES:
            raise SttInvalidConfigError('Unsupported message. Send binary audio frames, or {"type":"end"} to finish.')
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if data != {"type": "end"}:
            raise SttInvalidConfigError('Unsupported message. Send binary audio frames, or {"type":"end"} to finish.')

    # ------------------------------------------------------------------ transport helpers

    async def _receive(self, websocket: WebSocket) -> dict[str, Any]:
        try:
            async with asyncio.timeout(self._s.stt_idle_timeout_seconds):
                message = await websocket.receive()
        except TimeoutError:
            raise SttIdleTimeoutError() from None
        except RuntimeError:
            raise ClientGone() from None
        if message["type"] == "websocket.disconnect":
            raise ClientGone()
        return message

    async def _send(self, websocket: WebSocket, payload: dict[str, Any]) -> None:
        try:
            async with asyncio.timeout(self._s.stt_send_timeout_seconds):
                await websocket.send_json(payload)
        except Exception:  # timeout (stalled reader) or a closed connection: either way the client is gone
            raise ClientGone() from None

    async def _fail(self, websocket: WebSocket, request_id: str, exc: AppError) -> None:
        """Best-effort: tell the client why, then close. Only a safe code and message are sent."""
        try:
            async with asyncio.timeout(ERROR_SEND_TIMEOUT):
                await websocket.send_json(error_event(exc.code, exc.message, request_id, exc.details))
        except Exception:
            pass
        await self._close(websocket, getattr(exc, "close_code", 1011))

    @staticmethod
    async def _close(websocket: WebSocket, code: int) -> None:
        try:
            await websocket.close(code=code)
        except Exception:  # already closed
            pass

    # ------------------------------------------------------------------ metrics (privacy-safe)

    def _summary(self, stream_id: str, stats: _Stats) -> dict[str, Any]:
        audio_seconds = round(stats.audio_bytes / stats.bytes_per_second, 2)
        return {
            "stream_id": stream_id,
            "audio_seconds": audio_seconds,
            "partials": stats.partials,
            "finals": stats.finals,
            "first_partial_ms": None if stats.first_partial_ms is None else round(stats.first_partial_ms, 1),
            "first_final_ms": None if stats.first_final_ms is None else round(stats.first_final_ms, 1),
            "total_ms": round((self._clock() - stats.started) * 1000, 1),
        }

    def _log_finished(self, outcome: str, error_code: str | None, stats: _Stats) -> None:
        """One line per stream: outcome, language and counts only. Never audio, transcripts, keys or ids."""
        total_ms = (self._clock() - stats.started) * 1000
        logger.log(
            logging.INFO if outcome in ("completed", "cancelled") else logging.WARNING,
            "stt stream finished: outcome=%s error=%s language=%s audio_bytes=%d partials=%d finals=%d "
            "first_partial_ms=%s first_final_ms=%s total_ms=%.0f",
            outcome, error_code or "-", stats.language, stats.audio_bytes, stats.partials, stats.finals,
            "-" if stats.first_partial_ms is None else f"{stats.first_partial_ms:.0f}",
            "-" if stats.first_final_ms is None else f"{stats.first_final_ms:.0f}",
            total_ms,
        )
