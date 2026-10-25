"""WS /voice/stream orchestration: user text or audio -> Gemini reply -> sentence-by-sentence speech.

It composes the EXISTING services in-process and does not duplicate them: SttStreamService's provider and limiter
(Deepgram), ChatService.stream (Gemini, session history, its own limiter) and TtsService.prepare (Sarvam/Deepgram, its
own limiter). Each stage keeps its own concurrency limit; `VOICE_MAX_CONCURRENT_TURNS` bounds whole turns on top.

One turn, in order:
  1. config, then either a text message or raw PCM16 audio (STT slot held only while transcribing, then released)
  2. response phase, bounded by VOICE_TURN_TIMEOUT_SECONDS, with three supervised tasks:
       producer  Gemini tokens -> `reply_text` events -> complete sentences -> bounded queue
       consumer  queue -> TTS per sentence -> `audio_start` / binary MP3 / `audio_end`
       watcher   notices the client disconnecting even while nothing is being sent
  3. exactly one terminal event: `done`, or a fatal `error`

Whatever way a turn ends (done, error, timeout, client disconnect, cancellation) the three tasks are cancelled and
awaited, the Gemini stream, the TTS upstream and the STT session are closed, and every slot is released, all in
`finally` blocks. Nothing is accumulated: audio is relayed chunk by chunk and the sentence queue is bounded. User
text, transcripts, replies, audio, keys and provider messages are never logged.
"""

import asyncio
import json
import logging
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket
from pydantic import ValidationError

from app.chat_service import ChatService
from app.config import Settings
from app.errors import (
    AppError,
    LLMNotConfiguredError,
    SttInvalidAudioError,
    SttLimitExceededError,
    SttNotConfiguredError,
    SttProviderError,
    SttTimeoutError,
    TtsNotConfiguredError,
)
from app.limits import GenerationLimiter
from app.schemas import MAX_MESSAGE_CHARS
from app.streaming import DoneEvent, TokenEvent
from app.stt.base import AudioFormat, STTSession
from app.stt.protocol import final_event, partial_event
from app.stt.service import BURST_SECONDS, MAX_REALTIME_FACTOR, ClientGone, SttStreamService
from app.tts.service import TtsService
from app.voice.protocol import (
    MAX_CONTROL_MESSAGE_BYTES,
    VoiceCapacityError,
    VoiceConfigMessage,
    VoiceError,
    VoiceIdleTimeoutError,
    VoiceInvalidConfigError,
    VoiceInvalidMessageError,
    VoiceNoSpeechError,
    VoiceTextMessage,
    VoiceTranscriptTooLongError,
    VoiceTurnTimeoutError,
    audio_end_event,
    audio_start_event,
    done_event,
    error_event,
    ready_event,
    reply_text_event,
)
from app.voice.sentences import SentenceChunker

logger = logging.getLogger(__name__)

ERROR_SEND_TIMEOUT = 2.0  # best-effort delivery of the final error event
_END = object()  # queue sentinel: the reply is complete


class StageFailure(Exception):
    """A provider stage failed: carries the stage name and the (safe) AppError to report."""

    def __init__(self, stage: str, error: AppError) -> None:
        super().__init__(error.code)
        self.stage, self.error = stage, error


@dataclass
class _Turn:
    websocket: WebSocket
    request_id: str
    started: float
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    language: str = "-"
    session_id: str = ""
    mode: str = "-"  # text | audio
    model: str | None = None
    seq: int = 0
    last_partial: str | None = None
    pcm_bytes: int = 0
    audio_started: float = 0.0
    sentences: int = 0
    audio_bytes: int = 0
    tts_dead: bool = False
    terminal_sent: bool = False
    transcript_ms: float | None = None
    first_text_ms: float | None = None
    first_audio_ms: float | None = None
    system_prompt: str | None = None
    voice: str | None = None


class VoiceStreamService:
    def __init__(
        self,
        settings: Settings,
        stt: SttStreamService,
        chat: ChatService,
        tts: TtsService,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._s, self._stt, self._chat, self._tts, self._clock = settings, stt, chat, tts, clock
        # Turns are long-lived: when full, fail immediately (the client retries) instead of queueing.
        self.limiter = GenerationLimiter(settings.voice_max_concurrent_turns, 0.0, VoiceCapacityError)

    def create_session(
        self,
        *,
        session_id: str | None = None,
        agent_id: str | None = None,
        system_prompt: str | None = None,
        language: str | None = None,
        voice: str | None = None,
    ) -> dict[str, Any]:
        """Pre-bind or configure a voice session with agent prompt, language, and voice settings."""
        sid = session_id or uuid.uuid4().hex
        lang = language or "english"
        if voice and voice not in self._s.tts_allowed_voices:
            from app.errors import TtsInvalidVoiceError
            raise TtsInvalidVoiceError(f"Unsupported voice: {voice}")
        self._chat._store.bind_session(
            sid,
            system_prompt=system_prompt,
            language=lang,
            voice=voice,
            agent_id=agent_id,
        )
        return {
            "session_id": sid,
            "agent_id": agent_id,
            "language": lang,
            "voice": voice,
        }

    # ------------------------------------------------------------------ entry point

    async def run(self, websocket: WebSocket, request_id: str) -> None:
        if not self._origin_allowed(websocket.headers.get("origin")):
            logger.warning("Voice connection rejected: origin not allowed [%s]", request_id)
            await websocket.close(code=1008)  # before accept: the handshake is refused (HTTP 403)
            return

        await websocket.accept(
            headers=[
                (b"x-request-id", request_id.encode()),
                (b"x-content-type-options", b"nosniff"),
                (b"cache-control", b"no-store"),
            ]
        )
        turn = _Turn(websocket, request_id, started=self._clock())
        outcome, error_code, error_stage = "cancelled", None, None  # stays "cancelled" if the handler is cancelled
        try:
            async with self.limiter.slot():
                config = await self._read_config(turn)
                turn.language = config.language
                turn.session_id = config.session_id or uuid.uuid4().hex
                bound_session = self._chat._store.get(turn.session_id)
                if bound_session is not None:
                    turn.system_prompt = bound_session.system_prompt
                    turn.voice = config.voice or bound_session.voice
                else:
                    turn.voice = config.voice
                self._require_configured()
                await self._send(turn, ready_event(
                    request_id=request_id, session_id=turn.session_id, language=turn.language, sample_rate=config.sample_rate,
                ))
                text = await self._obtain_text(turn, config)
                try:
                    async with asyncio.timeout(self._s.voice_turn_timeout_seconds):
                        await self._respond(turn, text)
                except TimeoutError:
                    raise VoiceTurnTimeoutError() from None
                turn.terminal_sent = True
                await self._send(turn, self._done(turn))
            outcome = "completed"
            await self._close(websocket, 1000)
        except ClientGone:
            outcome = "cancelled"
        except StageFailure as failure:
            outcome, error_code, error_stage = self._outcome(failure.error), failure.error.code, failure.stage
            await self._fail(turn, failure.stage, failure.error)
        except AppError as exc:  # VoiceError, or the capacity error raised by the turn limiter
            error_stage = getattr(exc, "stage", "server")
            outcome, error_code = self._outcome(exc), exc.code
            await self._fail(turn, error_stage, exc)
        except Exception as exc:
            outcome, error_code, error_stage = "failed", "internal_error", "server"
            # Type and traceback FRAMES only: the exception message could contain user text or a transcript.
            logger.error(
                "Unexpected error in voice turn [%s]: %s\n%s",
                request_id, type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__)),
            )
            await self._fail(turn, "server", AppError())
        finally:
            self._log_finished(turn, outcome, error_code, error_stage)
            if outcome == "cancelled":
                await self._close(websocket, 1001)

    @staticmethod
    def _outcome(exc: AppError) -> str:
        return "timeout" if isinstance(exc, VoiceTurnTimeoutError) else "failed"

    def _require_configured(self) -> None:
        """Configuration problems are fatal before any billable work starts."""
        if self._chat.model is None:
            raise StageFailure("llm", LLMNotConfiguredError())
        if not self._tts.configured:
            raise StageFailure("tts", TtsNotConfiguredError())

    # ------------------------------------------------------------------ step 1: config and the user's words

    def _origin_allowed(self, origin: str | None) -> bool:
        if origin is None:
            return True  # not a browser: scripts and the Backend send no Origin header
        allowed = self._s.stt_origin_list  # the same browser allow-list as WS /stt/stream
        return "*" in allowed or origin in allowed

    async def _read_config(self, turn: _Turn) -> VoiceConfigMessage:
        message = await self._receive(turn)
        text = message.get("text")
        if text is None:
            raise VoiceInvalidConfigError("The first message must be a JSON config message, sent before any audio or text.")
        if len(text.encode("utf-8")) > MAX_CONTROL_MESSAGE_BYTES:
            raise VoiceInvalidConfigError("The config message is too large.")
        try:
            return VoiceConfigMessage.model_validate_json(text)
        except ValidationError as exc:
            # Field names and constraint messages only: submitted values are never echoed back.
            details = [{"field": ".".join(str(p) for p in err["loc"]) or "config", "message": err["msg"]} for err in exc.errors()]
            raise VoiceInvalidConfigError(details=details) from None

    async def _obtain_text(self, turn: _Turn, config: VoiceConfigMessage) -> str:
        message = await self._receive(turn)
        if message.get("bytes") is not None:
            turn.mode = "audio"
            return await self._transcribe_phase(turn, config, message["bytes"])
        turn.mode = "text"
        raw = message.get("text")
        if raw is None or len(raw.encode("utf-8")) > MAX_CONTROL_MESSAGE_BYTES:
            raise VoiceInvalidMessageError()
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if not isinstance(data, dict) or data.get("type") != "text":
            raise VoiceInvalidMessageError()
        try:
            return VoiceTextMessage.model_validate(data).text
        except ValidationError as exc:
            details = [{"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]} for err in exc.errors()]
            raise VoiceInvalidMessageError("The text message is invalid.", details=details) from None

    # ------------------------------------------------------------------ step 1b: speech to text (audio input)

    async def _transcribe_phase(self, turn: _Turn, config: VoiceConfigMessage, first_chunk: bytes) -> str:
        if config.sample_rate is None:
            raise VoiceInvalidConfigError("sample_rate is required in the config message when sending audio.")
        if not self._stt.configured:
            raise StageFailure("stt", SttNotConfiguredError())
        audio = AudioFormat(config.encoding, config.sample_rate, config.channels)
        try:
            async with self._stt.limiter.slot():  # held only while transcribing: released before Gemini starts
                session = await self._stt.provider.open(language=config.language, audio=audio)
                try:
                    finals = await self._transcribe(turn, session, audio, first_chunk)
                finally:
                    await session.aclose()  # closes the provider connection before the slot is released
        except VoiceError:
            raise
        except AppError as exc:
            raise StageFailure("stt", exc) from None
        text = " ".join(finals).strip()
        if not text:
            raise StageFailure("stt", VoiceNoSpeechError())
        if len(text) > MAX_MESSAGE_CHARS:
            raise StageFailure("stt", VoiceTranscriptTooLongError())
        turn.transcript_ms = (self._clock() - turn.started) * 1000
        return text

    async def _transcribe(self, turn: _Turn, session: STTSession, audio: AudioFormat, first_chunk: bytes) -> list[str]:
        finals: list[str] = []
        reader = asyncio.create_task(self._read_audio(turn, session, audio, first_chunk), name="voice-audio-reader")
        writer = asyncio.create_task(self._relay_transcripts(turn, session, finals), name="voice-transcript-writer")
        try:
            try:
                async with asyncio.timeout(self._s.stt_max_stream_seconds):
                    done, _ = await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_COMPLETED)
                    if reader not in done:
                        writer.result()  # the provider finished first: with an error, if it reported one
                        raise SttProviderError("The speech-to-text provider ended the stream unexpectedly.")
                    reader.result()  # a client error / disconnect surfaces here; a normal return means "end" was sent
                    try:
                        async with asyncio.timeout(self._s.stt_finish_timeout_seconds):
                            await writer  # the provider flushes its remaining final transcripts
                    except TimeoutError:
                        raise SttTimeoutError("The speech-to-text provider did not finish in time.") from None
            except TimeoutError:
                raise VoiceTurnTimeoutError("The maximum audio stream duration was reached.") from None
        finally:
            for task in (reader, writer):
                task.cancel()
            await asyncio.gather(reader, writer, return_exceptions=True)  # wait until both are really finished
        return finals

    async def _read_audio(self, turn: _Turn, session: STTSession, audio: AudioFormat, chunk: bytes) -> None:
        turn.audio_started = self._clock()
        while True:
            self._check_audio(turn, chunk, audio)
            await session.send_audio(chunk)  # backpressure: the next frame is read only after this returns
            message = await self._receive(turn)
            chunk = message.get("bytes")
            if chunk is None:
                self._check_end(message.get("text"))
                await session.finish()
                return

    def _check_audio(self, turn: _Turn, chunk: bytes, audio: AudioFormat) -> None:
        if not chunk:
            raise SttInvalidAudioError("Empty audio frame.")
        if turn.pcm_bytes == 0 and chunk[:4] == b"RIFF" and chunk[8:12] == b"WAVE":
            raise SttInvalidAudioError("Send raw PCM16 samples, not a WAV file: strip the 44-byte WAV header.")
        if len(chunk) > self._s.stt_max_chunk_bytes:
            raise SttLimitExceededError(f"Audio frame larger than {self._s.stt_max_chunk_bytes} bytes.")
        if len(chunk) % audio.frame_bytes:
            raise SttInvalidAudioError("Audio frames must contain whole 16-bit samples.")
        turn.pcm_bytes += len(chunk)
        seconds = turn.pcm_bytes / audio.bytes_per_second
        if seconds > self._s.stt_max_audio_seconds:
            raise SttLimitExceededError(f"The maximum audio duration of {self._s.stt_max_audio_seconds:g} s was reached.")
        if seconds > MAX_REALTIME_FACTOR * (self._clock() - turn.audio_started) + BURST_SECONDS:
            raise SttLimitExceededError("Audio is being sent much faster than real time.")

    @staticmethod
    def _check_end(text: str | None) -> None:
        if text is None or len(text.encode("utf-8")) > MAX_CONTROL_MESSAGE_BYTES:
            raise VoiceInvalidMessageError()
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if data != {"type": "end"}:
            raise VoiceInvalidMessageError()

    async def _relay_transcripts(self, turn: _Turn, session: STTSession, finals: list[str]) -> None:
        events = session.events()
        try:
            async for event in events:
                if event.kind == "partial":
                    if event.text == turn.last_partial:
                        continue  # the same hypothesis again is not news
                    turn.last_partial = event.text
                    turn.seq += 1
                    await self._send(turn, partial_event(turn.seq, event.text))
                else:
                    turn.last_partial = None
                    finals.append(event.text)
                    turn.seq += 1
                    await self._send(
                        turn, final_event(turn.seq, event.text, event.start, event.duration, event.speech_final, event.confidence)
                    )
        finally:
            await self._close_iterator(events)

    # ------------------------------------------------------------------ step 2: Gemini -> sentences -> speech

    async def _respond(self, turn: _Turn, text: str) -> None:
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=self._s.voice_sentence_queue_size)
        response_started = self._clock()
        producer = asyncio.create_task(self._produce(turn, text, queue), name="voice-llm")
        consumer = asyncio.create_task(self._consume(turn, queue), name="voice-tts")
        watcher = asyncio.create_task(self._watch_client(turn), name="voice-disconnect-watcher")
        tasks = (producer, consumer, watcher)
        try:
            pending = set(tasks)
            while True:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in tasks:  # a failure (or the client leaving) in any stage ends the turn
                    failure = task.exception() if task in done else None
                    if failure is not None:
                        raise failure
                if producer.done() and consumer.done():
                    break
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)  # waits until every upstream is really closed
        logger.debug("voice response phase took %.0f ms", (self._clock() - response_started) * 1000)

    async def _produce(self, turn: _Turn, text: str, queue: asyncio.Queue[Any]) -> None:
        # Never larger than what TTS accepts in one request (a very small TTS_MAX_TEXT_CHARS is clamped to the minimum).
        chunker = SentenceChunker(max(20, min(self._s.voice_max_sentence_chars, self._s.tts_max_text_chars)))
        events = self._chat.stream(
            message=text,
            session_id=turn.session_id,
            language=turn.language,
            request_id=turn.request_id,
            agent_prompt=turn.system_prompt,
        )
        try:
            async for event in events:
                if isinstance(event, TokenEvent):
                    if turn.first_text_ms is None:
                        turn.first_text_ms = (self._clock() - turn.started) * 1000
                    await self._send(turn, reply_text_event(event.text))
                    for sentence in chunker.feed(event.text):
                        await self._enqueue(turn, queue, sentence)
                elif isinstance(event, DoneEvent):
                    turn.model = event.model
            for sentence in chunker.flush():
                await self._enqueue(turn, queue, sentence)
            await queue.put(_END)  # the Gemini stream completed and the reply is stored in the session history
        except ClientGone:
            raise
        except AppError as exc:
            raise StageFailure("llm", exc) from None
        except Exception as exc:
            logger.error(
                "Unexpected error in the Gemini stage [%s]: %s\n%s",
                turn.request_id, type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__)),
            )
            raise StageFailure("llm", AppError()) from None
        finally:
            await self._close_iterator(events)  # releases the session lock and the Gemini slot

    @staticmethod
    async def _enqueue(turn: _Turn, queue: asyncio.Queue[Any], sentence: str) -> None:
        turn.sentences += 1
        if not turn.tts_dead:  # once speech failed the text keeps flowing, but nothing more is queued
            await queue.put(sentence)  # bounded: waits when speech is slower than Gemini

    async def _consume(self, turn: _Turn, queue: asyncio.Queue[Any]) -> None:
        index = 0
        while True:
            sentence = await queue.get()
            if sentence is _END:
                return
            if turn.tts_dead:
                continue  # drain, so the producer is never blocked on a full queue
            try:
                await self._speak(turn, sentence, index)
                index += 1
            except ClientGone:
                raise
            except AppError as exc:
                await self._tts_failed(turn, exc)
            except Exception as exc:
                logger.error(
                    "Unexpected error in the speech stage [%s]: %s\n%s",
                    turn.request_id, type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__)),
                )
                await self._tts_failed(turn, AppError())

    async def _speak(self, turn: _Turn, sentence: str, index: int) -> None:
        chunks = self._tts.prepare(text=sentence, language=turn.language, voice=turn.voice)  # validates; may raise
        started, size = False, 0
        try:
            async for chunk in chunks:
                if not started:
                    started = True
                    if turn.first_audio_ms is None:
                        turn.first_audio_ms = (self._clock() - turn.started) * 1000
                    await self._send(turn, audio_start_event(index, self._tts.content_type))
                size += len(chunk)
                turn.audio_bytes += len(chunk)
                await self._send(turn, binary=chunk)
        except AppError:
            if started:
                await self._best_effort(turn, audio_end_event(index, False, size))
            raise
        finally:
            await self._close_iterator(chunks)  # closes the TTS upstream before its slot is released
        await self._send(turn, audio_end_event(index, True, size))

    async def _tts_failed(self, turn: _Turn, exc: AppError) -> None:
        """Speech failed: say so once (non-fatal), stop speaking, and let the reply text finish."""
        turn.tts_dead = True
        await self._send(turn, error_event("tts", exc, turn.request_id, fatal=False))

    async def _watch_client(self, turn: _Turn) -> None:
        """Notice a disconnect while the server is busy generating. Further client messages are ignored."""
        while True:
            try:
                message = await turn.websocket.receive()
            except RuntimeError:
                raise ClientGone() from None
            if message["type"] == "websocket.disconnect":
                raise ClientGone()

    # ------------------------------------------------------------------ transport helpers

    async def _receive(self, turn: _Turn) -> dict[str, Any]:
        try:
            async with asyncio.timeout(self._s.stt_idle_timeout_seconds):
                message = await turn.websocket.receive()
        except TimeoutError:
            raise VoiceIdleTimeoutError() from None
        except RuntimeError:
            raise ClientGone() from None
        if message["type"] == "websocket.disconnect":
            raise ClientGone()
        return message

    async def _send(self, turn: _Turn, payload: dict[str, Any] | None = None, *, binary: bytes | None = None) -> None:
        try:
            async with turn.send_lock:  # two tasks send (text events and audio): one message at a time
                async with asyncio.timeout(self._s.stt_send_timeout_seconds):
                    if binary is not None:
                        await turn.websocket.send_bytes(binary)
                    else:
                        await turn.websocket.send_json(payload)
        except Exception:  # timeout (stalled reader) or a closed connection: either way the client is gone
            raise ClientGone() from None

    async def _best_effort(self, turn: _Turn, payload: dict[str, Any]) -> None:
        try:
            await self._send(turn, payload)
        except ClientGone:
            pass

    async def _fail(self, turn: _Turn, stage: str, exc: AppError) -> None:
        """Best-effort: send the single fatal error (unless a terminal event already went out), then close."""
        if not turn.terminal_sent:
            turn.terminal_sent = True
            try:
                async with asyncio.timeout(ERROR_SEND_TIMEOUT):
                    async with turn.send_lock:
                        await turn.websocket.send_json(error_event(stage, exc, turn.request_id, fatal=True))
            except Exception:
                pass
        await self._close(turn.websocket, getattr(exc, "close_code", 1011))

    @staticmethod
    async def _close(websocket: WebSocket, code: int) -> None:
        try:
            await websocket.close(code=code)
        except Exception:  # already closed
            pass

    @staticmethod
    async def _close_iterator(iterator: Any) -> None:
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                logger.debug("closing an upstream iterator failed", exc_info=False)

    # ------------------------------------------------------------------ metrics (privacy-safe)

    def _done(self, turn: _Turn) -> dict[str, Any]:
        def ms(value: float | None) -> float | None:
            return None if value is None else round(value, 1)

        return done_event(
            request_id=turn.request_id, session_id=turn.session_id, model=turn.model, language=turn.language,
            audio_complete=not turn.tts_dead, sentences=turn.sentences, audio_bytes=turn.audio_bytes,
            first_text_ms=ms(turn.first_text_ms), first_audio_ms=ms(turn.first_audio_ms),
            transcript_ms=ms(turn.transcript_ms), total_ms=ms((self._clock() - turn.started) * 1000),
        )

    def _log_finished(self, turn: _Turn, outcome: str, error_code: str | None, stage: str | None) -> None:
        """One line per turn: outcome, stage, mode, counts and timings. Never text, transcripts, audio, keys or ids."""
        def fmt(value: float | None) -> str:
            return "-" if value is None else f"{value:.0f}"

        logger.log(
            logging.INFO if outcome in ("completed", "cancelled") else logging.WARNING,
            "voice turn finished: outcome=%s stage=%s error=%s mode=%s language=%s sentences=%d audio_complete=%s "
            "audio_bytes=%d pcm_bytes=%d transcript_ms=%s first_text_ms=%s first_audio_ms=%s total_ms=%.0f",
            outcome, stage or "-", error_code or "-", turn.mode, turn.language, turn.sentences, not turn.tts_dead,
            turn.audio_bytes, turn.pcm_bytes, fmt(turn.transcript_ms), fmt(turn.first_text_ms), fmt(turn.first_audio_ms),
            (self._clock() - turn.started) * 1000,
        )
