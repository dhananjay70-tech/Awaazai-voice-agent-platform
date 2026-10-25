"""Scriptable fake TTS provider: deterministic, offline, and records exactly what the service did with it."""

import asyncio
from collections.abc import AsyncIterator


class FakeTTSProvider:
    name = "fake-tts"
    default_voice = "aura-2-thalia-en"
    content_type = "audio/mpeg"

    def __init__(
        self,
        chunks: list[bytes] | None = None,
        *,
        chunk_gates: list[asyncio.Event] | None = None,  # chunk i is produced only after chunk_gates[i] is set
        error: Exception | None = None,  # raised before chunk `error_after`
        error_after: int = 0,
        hang_after: int | None = None,  # after this many chunks, wait forever (a hung provider)
        cleanup_delay: float = 0.0,
    ) -> None:
        self.chunks = [b"ID3-chunk-1", b"chunk-2", b"chunk-3"] if chunks is None else chunks
        self.chunk_gates, self.error, self.error_after = chunk_gates, error, error_after
        self.hang_after, self.cleanup_delay = hang_after, cleanup_delay
        self.calls: list[tuple[str, str]] = []  # (text, voice)
        self.languages: list[str | None] = []
        self.started = self.closed = self.in_flight = self.max_in_flight = 0
        self.cancelled = False

    def default_voice_for(self, language: str) -> str:
        return self.default_voice

    async def stream(self, *, text: str, voice: str, language: str | None = None) -> AsyncIterator[bytes]:
        self.calls.append((text, voice))
        self.languages.append(language)
        self.started += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            for index, chunk in enumerate(self.chunks):
                if self.chunk_gates is not None and index < len(self.chunk_gates):
                    await self.chunk_gates[index].wait()
                if self.error is not None and index == self.error_after:
                    raise self.error
                yield chunk
                if self.hang_after is not None and index + 1 == self.hang_after:
                    await asyncio.Event().wait()
            if self.error is not None and self.error_after >= len(self.chunks):
                raise self.error
        except (asyncio.CancelledError, GeneratorExit):
            self.cancelled = True  # the consumer abandoned us: the "upstream cancelled" signal
            raise
        finally:
            if self.cleanup_delay:
                await asyncio.sleep(self.cleanup_delay)
            self.in_flight -= 1
            self.closed += 1
