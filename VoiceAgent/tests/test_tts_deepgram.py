"""DeepgramTtsProvider against a mocked HTTP transport (no network), plus TTS configuration validation."""

import asyncio
import json
import logging

import httpx
import pytest
from pydantic import ValidationError

from app.errors import (
    TtsAuthError,
    TtsBadResponseError,
    TtsProviderError,
    TtsRateLimitError,
    TtsTimeoutError,
    TtsUnavailableError,
)
from app.main import build_tts_provider
from app.tts.deepgram import DeepgramTtsProvider
from tests.conftest import make_settings

KEY = "dg-secret-key-do-not-leak"


def make_provider(handler, **overrides) -> DeepgramTtsProvider:
    values = dict(api_key=KEY, default_voice="aura-2-thalia-en", url="https://api.deepgram.com/v1/speak", bit_rate=48000, timeout_seconds=5)
    values.update(overrides)
    provider = DeepgramTtsProvider(**values)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


async def collect(provider, text="hello", voice="aura-2-thalia-en") -> list[bytes]:
    return [chunk async for chunk in provider.stream(text=text, voice=voice)]


def audio_response(chunks=(b"abc", b"def"), content_type="audio/mpeg", status=200):
    async def body():
        for chunk in chunks:
            yield chunk

    return httpx.Response(status, headers={"content-type": content_type}, content=body())


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 10))


def test_request_matches_the_documented_deepgram_api_and_streams_the_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["url"] = request.method, request.url
        seen["auth"], seen["body"] = request.headers["authorization"], json.loads(request.content)
        return audio_response()

    chunks = run(collect(make_provider(handler), text="Namaste!", voice="aura-2-zeus-en"))
    assert chunks == [b"abc", b"def"]
    assert seen["method"] == "POST" and seen["url"].path == "/v1/speak"
    assert dict(seen["url"].params) == {"model": "aura-2-zeus-en", "encoding": "mp3", "bit_rate": "48000"}
    assert seen["auth"] == f"Token {KEY}"
    assert seen["body"] == {"text": "Namaste!"}


@pytest.mark.parametrize(
    "status, error",
    [
        (401, TtsAuthError), (403, TtsAuthError),
        (402, TtsRateLimitError), (429, TtsRateLimitError),
        (408, TtsTimeoutError), (504, TtsTimeoutError),
        (400, TtsProviderError), (413, TtsProviderError), (422, TtsProviderError), (500, TtsProviderError), (503, TtsProviderError),
    ],
)
def test_http_status_maps_to_a_safe_error_and_the_body_is_never_exposed(status, error):
    def handler(request):
        return httpx.Response(status, json={"err_msg": f"detail echoing {KEY} and the text"})

    with pytest.raises(error) as caught:
        run(collect(make_provider(handler)))
    assert KEY not in caught.value.message and "detail" not in caught.value.message


def test_non_audio_200_response_is_rejected():
    with pytest.raises(TtsBadResponseError):
        run(collect(make_provider(lambda r: httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>"))))


def test_empty_chunks_from_the_provider_are_skipped():
    assert run(collect(make_provider(lambda r: audio_response(chunks=(b"", b"x", b""))))) == [b"x"]


def test_network_failure_is_tts_unavailable_without_leaking_details(caplog):
    caplog.set_level(logging.DEBUG)

    def handler(request):
        raise httpx.ConnectError(f"connection to {KEY} failed")

    with pytest.raises(TtsUnavailableError):
        run(collect(make_provider(handler)))
    assert KEY not in caplog.text and "ConnectError" in caplog.text


def test_provider_timeout_is_tts_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(TtsTimeoutError):
        run(collect(make_provider(handler)))


def test_connection_dropped_mid_audio_is_tts_unavailable():
    async def broken():
        yield b"abc"
        raise httpx.RemoteProtocolError("peer closed connection")

    provider = make_provider(lambda r: httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=broken()))

    async def scenario():
        received = []
        with pytest.raises(TtsUnavailableError):
            async for chunk in provider.stream(text="hi", voice="aura-2-thalia-en"):
                received.append(chunk)
        assert received == [b"abc"]

    run(scenario())


def test_closing_the_stream_early_closes_the_upstream_response():
    closed = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"first"
            await asyncio.Event().wait()

        async def aclose(self):
            closed.append(True)

    provider = make_provider(lambda r: httpx.Response(200, headers={"content-type": "audio/mpeg"}, stream=Body()))

    async def scenario():
        stream = provider.stream(text="hi", voice="aura-2-thalia-en")
        assert await anext(stream) == b"first"
        await stream.aclose()
        assert closed == [True]

    run(scenario())


def test_the_provider_is_built_only_when_a_key_is_configured_and_reuses_the_stt_key():
    assert build_tts_provider(make_settings()) is None
    provider = build_tts_provider(make_settings(deepgram_api_key=KEY))
    assert provider.default_voice == "aura-2-thalia-en" and provider.content_type == "audio/mpeg"
    assert provider._api_key == KEY
    run(provider.aclose())


# ---------------------------------------------------------------- configuration

def test_tts_defaults():
    s = make_settings()
    assert s.deepgram_tts_url == "https://api.deepgram.com/v1/speak"
    assert s.deepgram_tts_model == "aura-2-thalia-en"
    assert s.tts_allowed_voices == {"aura-2-thalia-en"}
    assert s.tts_max_text_chars == 2000 and s.tts_max_concurrent_requests == 4


@pytest.mark.parametrize(
    "overrides",
    [
        {"deepgram_tts_url": "http://api.deepgram.com/v1/speak"},
        {"deepgram_tts_url": "ftp://x"},
        {"deepgram_tts_model": "thalia"},
        {"deepgram_tts_model": "aura-2-thalia-en&encoding=wav"},
        {"deepgram_tts_voices": "aura-2-zeus-en,bad voice"},
        {"tts_max_text_chars": 2001},
        {"tts_max_text_chars": 0},
        {"tts_max_concurrent_requests": 0},
        {"tts_timeout_seconds": 0},
        {"deepgram_tts_bit_rate": 128000},
    ],
)
def test_invalid_tts_settings_are_rejected_at_startup(overrides):
    with pytest.raises(ValidationError):
        make_settings(**overrides)


def test_localhost_http_url_and_extra_voices_are_accepted():
    s = make_settings(deepgram_tts_url="http://127.0.0.1:9999/v1/speak", deepgram_tts_voices="aura-2-zeus-en, aura-asteria-en")
    assert s.tts_allowed_voices == {"aura-2-thalia-en", "aura-2-zeus-en", "aura-asteria-en"}
