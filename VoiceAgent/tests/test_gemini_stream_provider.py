"""GeminiProvider.stream() against a FAKE SDK client (no network, no key)."""

import asyncio
import logging

import pytest
from google.genai import types

from app.errors import LLMBadResponseError
from app.llm.base import ChatMessage
from app.llm.gemini import GeminiProvider
from tests.conftest import build_client
from tests.test_gemini_provider import ERROR_CASES, FAKE_KEY, SENTINEL, text_response


class FakeSDKStream:
    """Stands in for the object returned by `await client.aio.models.generate_content_stream(...)`."""

    def __init__(self, items, gates=None, error=None, error_at=None):
        self._items, self._gates, self._error, self._error_at = list(items), gates or [], error, error_at
        self._index = 0
        self.closed = False
        self.produced = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._error is not None and self._index == self._error_at:
            raise self._error
        if self._index >= len(self._items):
            raise StopAsyncIteration
        if self._index < len(self._gates):
            await self._gates[self._index].wait()
        item = self._items[self._index]
        self._index += 1
        self.produced += 1
        return item

    async def aclose(self):
        self.closed = True


class FakeStreamModels:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    async def generate_content_stream(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class FakeStreamSDKClient:
    def __init__(self, outcome):
        self.models = FakeStreamModels(outcome)
        client = self

        class Aio:
            models = client.models

            async def aclose(self_inner):
                pass

        self.aio = Aio()


def provider_for(outcome, **overrides):
    sdk = FakeStreamSDKClient(outcome)
    values = dict(api_key=FAKE_KEY, model="gemini-2.5-flash", timeout_seconds=5, temperature=0.7, max_output_tokens=512, client=sdk)
    values.update(overrides)
    return GeminiProvider(**values), sdk


def drain(provider, messages=None):
    async def go():
        return [chunk async for chunk in provider.stream(system_instruction="SYS", messages=messages or [ChatMessage("user", "hi")])]

    return asyncio.run(asyncio.wait_for(go(), 10))


# ---------------------------------------------------------------- happy path

def test_yields_text_chunks_in_order_and_skips_chunks_without_text():
    final = types.GenerateContentResponse(candidates=[types.Candidate(finish_reason=types.FinishReason.STOP)])  # no text
    stream = FakeSDKStream([text_response("Namaste "), text_response("duniya"), final])
    provider, _ = provider_for(stream)
    assert drain(provider) == ["Namaste ", "duniya"]
    assert stream.closed  # the SDK stream is always closed when we are done


def test_request_is_built_exactly_like_the_blocking_call():
    stream = FakeSDKStream([text_response("x")])
    provider, sdk = provider_for(stream, temperature=0.3, max_output_tokens=256)
    drain(provider, [ChatMessage("user", "q1"), ChatMessage("assistant", "a1"), ChatMessage("user", "q2")])
    (call,) = sdk.models.calls
    assert call["model"] == "gemini-2.5-flash"
    assert [(c.role, c.parts[0].text) for c in call["contents"]] == [("user", "q1"), ("model", "a1"), ("user", "q2")]
    assert call["config"].system_instruction == "SYS"
    assert call["config"].temperature == 0.3 and call["config"].max_output_tokens == 256
    assert call["config"].thinking_config.thinking_budget == 0


def test_chunks_are_passed_on_as_they_arrive_not_after_the_stream_ends():
    gates = [asyncio.Event(), asyncio.Event(), asyncio.Event()]
    stream = FakeSDKStream([text_response("a "), text_response("b "), text_response("c")], gates=gates)
    provider, _ = provider_for(stream)

    async def scenario():
        iterator = provider.stream(system_instruction="SYS", messages=[ChatMessage("user", "hi")])
        gates[0].set()
        assert await asyncio.wait_for(anext(iterator), 2) == "a "
        assert stream.produced == 1, "the SDK stream must not be read ahead of the consumer"
        gates[1].set()
        assert await asyncio.wait_for(anext(iterator), 2) == "b "
        gates[2].set()
        assert await asyncio.wait_for(anext(iterator), 2) == "c"
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)

    asyncio.run(scenario())


# ---------------------------------------------------------------- closing / cancelling stops the upstream stream

def test_closing_the_generator_closes_the_sdk_stream():
    gates = [asyncio.Event(), asyncio.Event(), asyncio.Event()]
    stream = FakeSDKStream([text_response("a "), text_response("b "), text_response("c")], gates=gates)
    provider, _ = provider_for(stream)

    async def scenario():
        iterator = provider.stream(system_instruction="SYS", messages=[ChatMessage("user", "hi")])
        gates[0].set()  # only the first chunk exists; the answer is still being generated
        assert await anext(iterator) == "a "
        assert not stream.closed
        await iterator.aclose()  # the consumer walks away mid-answer
        assert stream.closed and stream.produced == 1  # nothing further was read from upstream

    asyncio.run(scenario())


def test_cancelling_the_consuming_task_closes_the_sdk_stream():
    stream = FakeSDKStream([text_response("a "), text_response("b")], gates=[asyncio.Event(), asyncio.Event()])
    stream._gates[0].set()
    provider, _ = provider_for(stream)

    async def scenario():
        async def consume():
            async for _ in provider.stream(system_instruction="SYS", messages=[ChatMessage("user", "hi")]):
                pass

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)  # got "a ", now blocked waiting for chunk 2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed

    asyncio.run(scenario())


# ---------------------------------------------------------------- failures: same mapping as the blocking call

ids = lambda v: type(v).__name__ if not isinstance(v, type) else v.__name__


@pytest.mark.parametrize("raised,expected", ERROR_CASES, ids=ids)
def test_errors_when_opening_the_stream_are_translated(raised, expected):
    provider, _ = provider_for(raised)  # generate_content_stream() itself fails (bad key, retired model, ...)
    with pytest.raises(expected) as info:
        drain(provider)
    assert type(info.value) is expected and info.value.__cause__ is None


@pytest.mark.parametrize("raised,expected", ERROR_CASES, ids=ids)
def test_errors_in_the_middle_of_the_stream_are_translated(raised, expected):
    stream = FakeSDKStream([text_response("a "), text_response("b")], error=raised, error_at=1)
    provider, _ = provider_for(stream)
    received = []

    async def go():
        async for chunk in provider.stream(system_instruction="SYS", messages=[ChatMessage("user", "hi")]):
            received.append(chunk)

    with pytest.raises(expected):
        asyncio.run(asyncio.wait_for(go(), 10))
    assert received == ["a "] and stream.closed


BAD_STREAMS = {
    "no chunks at all": [],
    "chunks without text": [types.GenerateContentResponse(candidates=[types.Candidate(finish_reason=types.FinishReason.STOP)])],
    "safety blocked": [types.GenerateContentResponse(candidates=[types.Candidate(finish_reason=types.FinishReason.SAFETY)])],
    "prompt blocked": [types.GenerateContentResponse(
        prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=types.BlockedReason.SAFETY))],
    "blank text only": [text_response("   "), text_response("")],
}


@pytest.mark.parametrize("name", list(BAD_STREAMS))
def test_empty_or_blocked_streams_raise_bad_response(name, caplog):
    stream = FakeSDKStream(BAD_STREAMS[name])
    provider, _ = provider_for(stream)
    with caplog.at_level(logging.WARNING), pytest.raises(LLMBadResponseError):
        drain(provider)
    assert "Gemini returned no usable text: reason=" in caplog.text  # category only
    assert stream.closed


# ---------------------------------------------------------------- secrets

@pytest.mark.parametrize("opening", [True, False])
@pytest.mark.parametrize("raised,expected", ERROR_CASES, ids=ids)
def test_no_secrets_or_provider_details_reach_stream_responses_or_logs(raised, expected, opening, caplog):
    stream = raised if opening else FakeSDKStream([text_response("Hello "), text_response("there")], error=raised, error_at=1)
    provider, _ = provider_for(stream)
    with build_client(provider) as client:
        caplog.set_level(logging.DEBUG)
        response = client.post("/chat/stream", json={"message": "PRIVATE-user-message-777", "session_id": "private-session"})
    for text in (response.text, caplog.text):
        assert SENTINEL not in text and FAKE_KEY not in text
        assert "PRIVATE-user-message-777" not in text
        assert "Traceback" not in text
    # The client's own session id is echoed back to that client in the `start` event, but must never reach the logs.
    assert "private-session" not in caplog.text
    assert expected.code in response.text
