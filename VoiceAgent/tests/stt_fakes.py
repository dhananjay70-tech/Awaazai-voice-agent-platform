"""Scriptable fake STT provider: deterministic, offline, and records exactly what the service did with it."""

import asyncio
from collections.abc import AsyncIterator

from app.stt.base import AudioFormat, TranscriptEvent

_END = object()


def partial(text: str, start: float = 0.0, duration: float = 0.5) -> TranscriptEvent:
    return TranscriptEvent("partial", text, start, duration)


def final(text: str, speech_final: bool = False, start: float = 0.0, duration: float = 1.0, confidence: float | None = 0.98) -> TranscriptEvent:
    return TranscriptEvent("final", text, start, duration, speech_final, confidence)


class FakeSTTSession:
    """Plays a script: `on_chunk[n]` events are emitted when the n-th audio chunk (1-based) arrives, `on_finish`
    events when the client ends the stream. Every interaction is recorded for assertions."""

    def __init__(self, on_chunk=None, on_finish=None, error_at_chunk=None, error=None, end_after_chunk=None,
                 hang_on_finish=False, send_delay=0.0, send_gate=None, close_delay=0.0):
        self.send_gate = send_gate  # when set, send_audio() blocks until the test opens it (simulates a slow provider)
        self.close_delay = close_delay  # how long closing the provider connection takes
        self.on_chunk = on_chunk or {}
        self.on_finish = on_finish or []
        self.error_at_chunk, self.error = error_at_chunk, error
        self.end_after_chunk = end_after_chunk  # the provider ends the stream by itself after this many chunks
        self.hang_on_finish = hang_on_finish
        self.send_delay = send_delay
        self.audio: list[bytes] = []
        self.finished = False
        self.closed = False
        self.events_cancelled = False
        self.send_cancelled = False
        self._queue: asyncio.Queue = asyncio.Queue()

    async def send_audio(self, chunk: bytes) -> None:
        try:
            if self.send_gate is not None:
                await self.send_gate.wait()
            if self.send_delay:
                await asyncio.sleep(self.send_delay)
        except asyncio.CancelledError:
            self.send_cancelled = True
            raise
        self.audio.append(chunk)
        n = len(self.audio)
        if self.error_at_chunk == n:
            self._queue.put_nowait(self.error)
            return
        for event in self.on_chunk.get(n, []):
            self._queue.put_nowait(event)
        if self.end_after_chunk == n:
            self._queue.put_nowait(_END)

    async def finish(self) -> None:
        self.finished = True
        for event in self.on_finish:
            self._queue.put_nowait(event)
        if not self.hang_on_finish:
            self._queue.put_nowait(_END)

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        try:
            while True:
                item = await self._queue.get()
                if item is _END:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield item
        except (asyncio.CancelledError, GeneratorExit):
            self.events_cancelled = True  # the consumer cancelled it, or closed it because it stopped consuming
            raise

    async def aclose(self) -> None:
        if self.close_delay:
            await asyncio.sleep(self.close_delay)
        self.closed = True

    @property
    def audio_bytes(self) -> int:
        return sum(len(c) for c in self.audio)


class FakeSTTProvider:
    name = "fake-stt"
    model = "fake-stt-model"

    def __init__(self, session_factory=None, open_error=None, open_delay=0.0, **session_kwargs):
        self._factory = session_factory or (lambda: FakeSTTSession(**session_kwargs))
        self.open_error = open_error
        self.open_delay = open_delay
        self.opened: list[tuple[str, AudioFormat]] = []
        self.sessions: list[FakeSTTSession] = []

    async def open(self, *, language: str, audio: AudioFormat) -> FakeSTTSession:
        if self.open_delay:
            await asyncio.sleep(self.open_delay)
        if self.open_error is not None:
            raise self.open_error
        self.opened.append((language, audio))
        session = self._factory()
        self.sessions.append(session)
        return session

    @property
    def last(self) -> FakeSTTSession:
        return self.sessions[-1]
