"""Deepgram live streaming STT over its documented WebSocket API (wss://api.deepgram.com/v1/listen).

Protocol facts, taken from Deepgram's official AsyncAPI spec and docs (not from memory):
- Auth: `Authorization: Token <API_KEY>` header on the WebSocket handshake.
- Query parameters: model, language, encoding=linear16, sample_rate, channels, interim_results, endpointing, punctuate.
- Client -> server: binary audio frames; JSON text frames {"type":"Finalize"} (flush) and {"type":"CloseStream"} (end).
- Server -> client: JSON "Results" (channel.alternatives[0].transcript, is_final, speech_final, start, duration),
  plus "Metadata", "UtteranceEnd", "SpeechStarted" (ignored) and non-fatal "Error".
- Languages (Nova-3): `en` (also en-IN, en-US, en-GB...), `hi`, and `multi`, the code-switching mode that covers
  English, Spanish, French, German, Hindi, Russian, Portuguese, Japanese, Italian and Dutch. Deepgram recommends
  endpointing=100 for `multi`. There is NO documented Hinglish mode and no `hi-Latn` for Nova-3 (it exists only for
  legacy models), so the script (Devanagari or Roman) in which Hindi words come back is not documented either. We
  return exactly what Deepgram sends and never translate or transliterate it.
- Interim results have is_final=false and may change; is_final=true results are stable, non-overlapping segments.
- Deepgram closes the connection after ~10 s without audio (close code 1011, NET-0001); undecodable audio closes it
  with 1008 (DATA-0000).

We talk to the WebSocket directly with the `websockets` library (already installed, pinned in requirements.txt)
instead of adding the Deepgram SDK: the protocol is small and documented, and direct control gives deterministic
connection teardown on cancellation. The API key is only ever placed in the handshake header: it is never logged.
"""

import asyncio
import json
import logging
import math
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

from websockets import exceptions as ws_exceptions
from websockets.asyncio.client import ClientConnection, connect

from app.errors import (
    SttAuthError,
    SttBadResponseError,
    SttError,
    SttInvalidAudioError,
    SttProviderError,
    SttRateLimitError,
    SttTimeoutError,
    SttUnavailableError,
)
from app.stt.base import AudioFormat, TranscriptEvent

logger = logging.getLogger(__name__)

_MAX_MESSAGE_BYTES = 1_048_576  # no legitimate Deepgram message is larger; refuse anything bigger


class DeepgramProvider:
    name = "deepgram"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        url: str,
        language_codes: dict[str, str],
        endpointing_ms: int,
        connect_timeout_seconds: float,
        endpointing_ms_by_language: dict[str, int] | None = None,  # overrides `endpointing_ms` for these languages
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._url = url
        self._language_codes = language_codes
        self._endpointing_ms = endpointing_ms
        self._endpointing_by_language = endpointing_ms_by_language or {}
        self._connect_timeout = connect_timeout_seconds

    def language_code(self, language: str) -> str:
        return self._language_codes[language]

    async def open(self, *, language: str, audio: AudioFormat) -> "DeepgramSession":
        query = urlencode(
            {
                "model": self.model,
                "language": self.language_code(language),
                "encoding": audio.encoding,
                "sample_rate": audio.sample_rate,
                "channels": audio.channels,
                "interim_results": "true",
                "endpointing": self._endpointing_by_language.get(language, self._endpointing_ms),
                "punctuate": "true",
            }
        )
        try:
            connection = await connect(
                f"{self._url}?{query}",
                additional_headers={"Authorization": f"Token {self._api_key}"},
                open_timeout=self._connect_timeout,
                max_size=_MAX_MESSAGE_BYTES,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise self._translate_connect_error(exc) from None  # provider details are dropped, never chained
        return DeepgramSession(connection)

    @staticmethod
    def _translate_connect_error(exc: Exception) -> SttError:
        status = None
        if isinstance(exc, ws_exceptions.InvalidStatus):
            status = exc.response.status_code
            if status in (401, 403):
                category, error = "auth", SttAuthError()
            elif status == 429:
                category, error = "rate_limit", SttRateLimitError()
            elif status >= 500:
                category, error = "server_error", SttUnavailableError()
            else:
                category, error = "client_error", SttProviderError()
        elif isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            category, error = "timeout", SttTimeoutError()
        elif isinstance(exc, OSError):
            category, error = "network", SttUnavailableError()
        else:
            category, error = "unexpected", SttProviderError()
        logger.warning("Deepgram connection failed: category=%s http_status=%s", category, status)  # no detail text
        return error

    async def aclose(self) -> None:
        return None  # one connection per session; nothing shared to release


class DeepgramSession:
    def __init__(self, connection: ClientConnection) -> None:
        self._ws = connection
        self._closed = False
        self._finish_requested = False

    async def send_audio(self, chunk: bytes) -> None:
        try:
            await self._ws.send(chunk)
        except ws_exceptions.ConnectionClosed as exc:
            raise _error_for_close(exc) from None

    async def finish(self) -> None:
        """Flush what Deepgram has buffered, then end the stream; Deepgram answers with the remaining finals."""
        self._finish_requested = True
        try:
            await self._ws.send(json.dumps({"type": "Finalize"}))
            await self._ws.send(json.dumps({"type": "CloseStream"}))
        except ws_exceptions.ConnectionClosed:
            pass  # it already ended; events() will report why if it was a failure

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        try:
            async for raw in self._ws:
                event = _parse_message(raw)
                if event is not None:
                    yield event
            if not self._finish_requested:
                # `websockets` counts close codes 1000/1001 as a normal close, but the provider ended the stream
                # before we asked it to: that is a failure for the client, not a completed transcript.
                code = self._ws.close_code
                raise SttUnavailableError() if code == 1001 else SttProviderError("The speech-to-text provider ended the stream unexpectedly.")
        except ws_exceptions.ConnectionClosed as exc:
            raise _error_for_close(exc) from None
        except ws_exceptions.WebSocketException:
            raise SttProviderError() from None

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._ws.close()
        except Exception:  # best effort: the connection is being abandoned anyway
            logger.debug("closing the Deepgram connection failed", exc_info=False)


def _error_for_close(exc: ws_exceptions.ConnectionClosed) -> SttError:
    """Map how Deepgram ended the connection to one of our safe errors (the close reason text is never used)."""
    code = exc.rcvd.code if exc.rcvd is not None else None
    if code == 1000:
        return SttProviderError("The speech-to-text provider ended the stream unexpectedly.")
    if code == 1008:  # DATA-0000: the payload could not be decoded as audio
        return SttInvalidAudioError("The speech-to-text provider could not decode the audio.")
    if code in (None, 1001, 1006, 1012, 1013):
        return SttUnavailableError()
    logger.warning("Deepgram closed the stream: code=%s", code)
    return SttProviderError()


def _number(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SttBadResponseError()
    return float(value)


def _parse_message(raw: str | bytes) -> TranscriptEvent | None:
    """Turn one Deepgram message into a TranscriptEvent, ignore the ones we do not need, reject malformed ones."""
    if isinstance(raw, bytes):
        raise SttBadResponseError()  # the transcription API never sends binary frames
    try:
        data = json.loads(raw)
    except ValueError:
        raise SttBadResponseError() from None
    if not isinstance(data, dict):
        raise SttBadResponseError()

    kind = data.get("type")
    if kind == "Error":  # documented as non-fatal ("fatal failures close the socket instead")
        variant = data.get("variant")
        logger.warning("Deepgram reported a non-fatal error: variant=%s", variant if isinstance(variant, str) else "?")
        return None
    if kind != "Results":
        return None  # Metadata, UtteranceEnd, SpeechStarted and any future message types

    try:
        alternative = data["channel"]["alternatives"][0]
        text = alternative["transcript"]
        is_final = data["is_final"]
    except (KeyError, IndexError, TypeError):
        raise SttBadResponseError() from None
    speech_final = data.get("speech_final", False)
    if not isinstance(text, str) or not isinstance(is_final, bool) or not isinstance(speech_final, bool):
        raise SttBadResponseError()

    text = text.strip()
    if not text:
        return None  # silence: Deepgram reports empty transcripts while nobody is speaking
    return TranscriptEvent(
        kind="final" if is_final else "partial",
        text=text,
        start=_number(data.get("start"), 0.0),
        duration=_number(data.get("duration"), 0.0),
        speech_final=speech_final and is_final,
        confidence=_number(alternative.get("confidence")),
    )
