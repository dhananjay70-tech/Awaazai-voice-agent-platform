"""Test fixtures: an isolated app that ignores any developer .env file and never touches the network."""

import asyncio
import re
from collections.abc import AsyncIterator, Callable, Sequence

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.base import ChatMessage
from app.main import create_app


def make_settings(**overrides) -> Settings:
    # gemini_api_key=None: a developer's real key (in .env or the shell) can never leak into tests.
    values = {"environment": "test", "log_level": "WARNING", "gemini_api_key": None, "deepgram_api_key": None}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # _env_file=None: never read a developer's real .env


class FakeProvider:
    """Deterministic stand-in for Gemini: records every call, can fail, and can be paused to test concurrency."""

    model = "fake-model"

    def __init__(
        self,
        reply: Callable[[int], str] | None = None,
        error: Exception | None = None,
        gate: asyncio.Event | None = None,
        *,
        chunks: list[str] | None = None,  # stream(): exact chunks to emit (default: the reply split into words)
        chunk_gates: list[asyncio.Event] | None = None,  # stream(): chunk i waits for chunk_gates[i]
        stream_error: Exception | None = None,  # stream(): raised before chunk `error_after`
        error_after: int = 0,
        hang_after: int | None = None,  # stream(): after this many chunks, wait forever (a hung Gemini)
        on_chunk: Callable[[int], None] | None = None,  # stream(): called just before chunk i is yielded
        chunk_delay: float = 0.0,  # stream(): real seconds to wait before each chunk
        cleanup_delay: float = 0.0,  # stream(): seconds its cleanup (closing the upstream) takes
    ) -> None:
        self._reply = reply or (lambda n: f"fake-reply-{n}")
        self.error = error
        self.gate = gate  # when set, generate() waits until the test opens it
        self._chunks, self.chunk_gates = chunks, chunk_gates
        self.stream_error, self.error_after, self.hang_after, self.on_chunk = stream_error, error_after, hang_after, on_chunk
        self.chunk_delay = chunk_delay
        self.cleanup_delay, self.cleanup_done = cleanup_delay, False
        self.calls: list[tuple[str, list[ChatMessage]]] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.closed = False
        # stream() bookkeeping, used to prove cleanup really happened
        self.chunks_sent = 0
        self.streams_started = 0
        self.streams_closed = 0
        self.stream_cancelled = False

    async def generate(self, *, system_instruction: str, messages: Sequence[ChatMessage]) -> str:
        self.calls.append((system_instruction, list(messages)))
        number = len(self.calls)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.gate is not None:
                await self.gate.wait()
            if self.error is not None:
                raise self.error
            return self._reply(number)
        finally:
            self.in_flight -= 1

    async def stream(self, *, system_instruction: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        self.calls.append((system_instruction, list(messages)))
        number = len(self.calls)
        self.streams_started += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            chunks = self._chunks if self._chunks is not None else re.findall(r"\S+\s*", self._reply(number))
            for index, chunk in enumerate(chunks):
                if self.chunk_gates is not None and index < len(self.chunk_gates):
                    await self.chunk_gates[index].wait()
                if self.chunk_delay:
                    await asyncio.sleep(self.chunk_delay)
                if self.stream_error is not None and index == self.error_after:
                    raise self.stream_error
                if self.on_chunk is not None:
                    self.on_chunk(index)
                yield chunk
                self.chunks_sent += 1
                if self.hang_after is not None and index + 1 == self.hang_after:
                    await asyncio.Event().wait()  # never set: simulates an upstream that stopped answering
            if self.stream_error is not None and self.error_after >= len(chunks):
                raise self.stream_error
        except (asyncio.CancelledError, GeneratorExit):
            self.stream_cancelled = True  # the consumer abandoned us: this is the "upstream cancelled" signal
            raise
        finally:
            if self.cleanup_delay:
                await asyncio.sleep(self.cleanup_delay)  # e.g. closing a network connection takes a moment
            self.cleanup_done = True
            self.in_flight -= 1
            self.streams_closed += 1

    async def aclose(self) -> None:
        self.closed = True


def build_client(provider=None, **settings_overrides) -> TestClient:
    return TestClient(create_app(make_settings(**settings_overrides), llm_provider=provider), raise_server_exceptions=False)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def client(settings) -> TestClient:
    """The Phase 1 fixture: no provider configured (no API key), exactly as before."""
    with TestClient(create_app(settings=settings)) as test_client:
        yield test_client


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def chat_client(provider):
    """An app wired to a FakeProvider."""
    with build_client(provider) as test_client:
        yield test_client
