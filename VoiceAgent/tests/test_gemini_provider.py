"""GeminiProvider against a FAKE SDK client: request shape, error mapping, response parsing, secret hygiene.

Nothing here touches the network or needs a real key.
"""

import asyncio
import logging

import httpx
import pytest
from google.genai import errors as genai_errors
from google.genai import types

import app.llm.gemini as gemini_module
from app.errors import (
    LLMAuthError,
    LLMBadResponseError,
    LLMModelUnavailableError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.base import ChatMessage
from app.llm.gemini import GeminiProvider
from tests.conftest import build_client

FAKE_KEY = "fake-test-key-NOT-A-REAL-KEY-0123456789"
SENTINEL = "SENSITIVE-provider-message-9f2c"


def text_response(text="Namaste!", finish=types.FinishReason.STOP):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text=text)]), finish_reason=finish)]
    )


class _Models:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if callable(self.outcome):
            return await self.outcome()
        return self.outcome


class FakeSDKClient:
    def __init__(self, outcome=None):
        self.models = _Models(outcome if outcome is not None else text_response())
        self.closed = False
        client = self

        class Aio:
            models = client.models

            async def aclose(self_inner):
                client.closed = True

        self.aio = Aio()


def make_provider(outcome=None, **overrides):
    sdk = FakeSDKClient(outcome)
    values = dict(api_key=FAKE_KEY, model="gemini-2.5-flash", timeout_seconds=5, temperature=0.7, max_output_tokens=512, client=sdk)
    values.update(overrides)
    return GeminiProvider(**values), sdk


def generate(provider, messages=None, system="SYSTEM-INSTRUCTION"):
    return asyncio.run(provider.generate(system_instruction=system, messages=messages or [ChatMessage("user", "hi")]))


# ---------------------------------------------------------------- request construction

def test_request_shape():
    provider, sdk = make_provider(temperature=0.3, max_output_tokens=256)
    messages = [ChatMessage("user", "q1"), ChatMessage("assistant", "a1"), ChatMessage("user", "q2")]
    assert generate(provider, messages, system="TRUSTED") == "Namaste!"

    (call,) = sdk.models.calls
    assert call["model"] == "gemini-2.5-flash"
    assert [(c.role, c.parts[0].text) for c in call["contents"]] == [("user", "q1"), ("model", "a1"), ("user", "q2")]
    config = call["config"]
    assert config.system_instruction == "TRUSTED"  # passed as the system instruction, not as a message
    assert all("TRUSTED" not in c.parts[0].text for c in call["contents"])
    assert config.temperature == 0.3 and config.max_output_tokens == 256
    assert config.thinking_config.thinking_budget == 0  # latency: no hidden thinking step


def test_model_attribute_reflects_configuration():
    provider, _ = make_provider(model="gemini-2.5-flash")
    assert provider.model == "gemini-2.5-flash"


def test_real_sdk_client_gets_key_and_millisecond_timeout(monkeypatch):
    captured = {}

    class RecordingClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(gemini_module.genai, "Client", RecordingClient)
    GeminiProvider(api_key=FAKE_KEY, model="m", timeout_seconds=7.5, temperature=0.5, max_output_tokens=100)
    assert captured["api_key"] == FAKE_KEY
    assert captured["http_options"].timeout == 7500  # SDK expects milliseconds


def test_aclose_closes_the_sdk_client_and_swallows_errors():
    provider, sdk = make_provider()
    asyncio.run(provider.aclose())
    assert sdk.closed

    broken, sdk2 = make_provider()
    sdk2.aio.aclose = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    asyncio.run(broken.aclose())  # must not raise during shutdown


# ---------------------------------------------------------------- response parsing

def test_reply_text_is_stripped():
    provider, _ = make_provider(text_response("  hello  \n"))
    assert generate(provider) == "hello"


def test_truncated_reply_with_text_is_accepted():
    provider, _ = make_provider(text_response("partial answ", finish=types.FinishReason.MAX_TOKENS))
    assert generate(provider) == "partial answ"


BAD_RESPONSES = {
    "empty candidates": types.GenerateContentResponse(candidates=[]),
    "no candidates": types.GenerateContentResponse(),
    "blank text": text_response("   \n  "),
    "safety blocked": types.GenerateContentResponse(candidates=[types.Candidate(finish_reason=types.FinishReason.SAFETY)]),
    "prompt blocked": types.GenerateContentResponse(
        prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=types.BlockedReason.SAFETY)
    ),
    "not a response object at all": object(),
    "None": None,
}


@pytest.mark.parametrize("name", list(BAD_RESPONSES))
def test_empty_or_malformed_responses_raise_bad_response(name):
    outcome = BAD_RESPONSES[name]
    sdk = FakeSDKClient()
    sdk.models.outcome = outcome
    provider = GeminiProvider(api_key=FAKE_KEY, model="m", timeout_seconds=5, temperature=0.5, max_output_tokens=100, client=sdk)
    with pytest.raises(LLMBadResponseError):
        generate(provider)


def test_bad_response_reason_is_logged_without_content(caplog):
    provider, sdk = make_provider()
    sdk.models.outcome = BAD_RESPONSES["safety blocked"]
    with caplog.at_level(logging.WARNING), pytest.raises(LLMBadResponseError):
        generate(provider)
    assert "reason=finish_safety" in caplog.text


# ---------------------------------------------------------------- error mapping

def api_error(cls, code, status="STATUS", message=SENTINEL):
    return cls(code, {"error": {"code": code, "message": message, "status": status}})


ERROR_CASES = [
    # (what the SDK/network raises, expected safe error)
    (api_error(genai_errors.ClientError, 401, "UNAUTHENTICATED"), LLMAuthError),
    (api_error(genai_errors.ClientError, 403, "PERMISSION_DENIED"), LLMAuthError),
    (api_error(genai_errors.ClientError, 400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key."), LLMAuthError),
    (api_error(genai_errors.ClientError, 429, "RESOURCE_EXHAUSTED"), LLMRateLimitError),
    (api_error(genai_errors.ClientError, 408, "DEADLINE_EXCEEDED"), LLMTimeoutError),
    (api_error(genai_errors.ServerError, 504, "DEADLINE_EXCEEDED"), LLMTimeoutError),
    (api_error(genai_errors.ServerError, 500, "INTERNAL"), LLMUnavailableError),
    (api_error(genai_errors.ServerError, 503, "UNAVAILABLE"), LLMUnavailableError),
    (api_error(genai_errors.ClientError, 404, "NOT_FOUND", "model is no longer available to new users"), LLMModelUnavailableError),
    (api_error(genai_errors.ClientError, 400, "INVALID_ARGUMENT", "bad request body"), LLMProviderError),
    (asyncio.TimeoutError(), LLMTimeoutError),
    (httpx.ReadTimeout(SENTINEL), LLMTimeoutError),
    (httpx.ConnectTimeout(SENTINEL), LLMTimeoutError),
    (httpx.ConnectError(SENTINEL), LLMUnavailableError),
    (httpx.RemoteProtocolError(SENTINEL), LLMUnavailableError),
    (ConnectionResetError(SENTINEL), LLMUnavailableError),
    (RuntimeError(SENTINEL), LLMProviderError),
    (ValueError(SENTINEL), LLMProviderError),
]


@pytest.mark.parametrize("raised,expected", ERROR_CASES, ids=lambda v: type(v).__name__ if not isinstance(v, type) else v.__name__)
def test_errors_are_translated(raised, expected):
    provider, _ = make_provider(raised)
    with pytest.raises(expected) as info:
        generate(provider)
    assert type(info.value) is expected
    assert info.value.__cause__ is None and info.value.__suppress_context__  # the raw provider error is not chained


def test_real_timeout_is_enforced_when_the_sdk_hangs(monkeypatch):
    monkeypatch.setattr(GeminiProvider, "_TIMEOUT_MARGIN_SECONDS", 0)

    async def hang():
        await asyncio.sleep(10)

    provider, _ = make_provider(hang, timeout_seconds=0.05)
    with pytest.raises(LLMTimeoutError):
        generate(provider)


def test_cancellation_is_not_swallowed():
    async def scenario():
        started = asyncio.Event()

        async def hang():
            started.set()
            await asyncio.sleep(10)

        provider, _ = make_provider(hang)
        task = asyncio.create_task(provider.generate(system_instruction="s", messages=[ChatMessage("user", "hi")]))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


# ---------------------------------------------------------------- secret hygiene (end to end through the API)

@pytest.mark.parametrize("raised,expected", ERROR_CASES, ids=lambda v: type(v).__name__ if not isinstance(v, type) else v.__name__)
def test_no_secrets_or_provider_details_reach_responses_or_logs(raised, expected, caplog):
    provider, _ = make_provider(raised)
    with caplog.at_level(logging.DEBUG), build_client(provider) as client:
        response = client.post("/chat", json={"message": "PRIVATE-user-message-777", "session_id": "private-session"})
    assert response.status_code == expected.status_code
    assert response.json()["error"]["code"] == expected.code
    for text in (response.text, caplog.text):
        assert SENTINEL not in text  # provider message never exposed
        assert FAKE_KEY not in text
        assert "PRIVATE-user-message-777" not in text
        assert "private-session" not in text
        assert "Traceback" not in text
