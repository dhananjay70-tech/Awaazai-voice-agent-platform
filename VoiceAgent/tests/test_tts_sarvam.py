"""Sarvam Bulbul TTS provider (mocked HTTP, no network), provider switching, and per-language speaker/code mapping."""

import asyncio
import json
import logging
import os

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import VOICEAGENT_DIR, Settings
from app.errors import (
    TtsAuthError,
    TtsBadResponseError,
    TtsProviderError,
    TtsRateLimitError,
    TtsTimeoutError,
    TtsUnavailableError,
)
from app.main import build_tts_provider, create_app
from app.tts.deepgram import DeepgramTtsProvider
from app.tts.sarvam import SarvamTtsProvider
from tests.conftest import make_settings

KEY = "sarvam-secret-key-do-not-leak"
ENGLISH = "Hello! I can help you book an appointment and answer your questions."
HINDI = "नमस्ते! मैं आपकी मदद कर सकता हूँ। आप क्या जानना चाहते हैं?"
HINGLISH = "Namaste! Main aapki appointment book karne mein help kar sakta hoon."


def sarvam_settings(**overrides):
    values = {"tts_provider": "sarvam", "sarvam_api_key": KEY}
    values.update(overrides)
    return make_settings(**values)


def install_transport(app_or_provider, handler):
    provider = getattr(getattr(app_or_provider, "state", None), "tts_service", None)
    provider = provider._provider if provider is not None else app_or_provider
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


def audio_response(chunks=(b"ID3", b"audio"), content_type="audio/mpeg", status=200):
    async def body():
        for chunk in chunks:
            yield chunk

    return httpx.Response(status, headers={"content-type": content_type}, content=body())


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 10))


async def collect(provider, text=ENGLISH, voice="dev_en_conversational", language="english") -> list[bytes]:
    return [chunk async for chunk in provider.stream(text=text, voice=voice, language=language)]


# ---------------------------------------------------------------- language and speaker mapping (the documented parameters)

@pytest.mark.parametrize(
    "language, text, code, speaker",
    [
        ("english", ENGLISH, "en-IN", "dev_en_conversational"),
        ("hindi", HINDI, "hi-IN", "kavya_hi_conversational"),  # Devanagari input
        ("hinglish", HINGLISH, "hi-IN", "simran_enhi_customer"),  # romanised Hindi mixed with English
    ],
)
def test_each_language_sends_its_documented_code_and_default_speaker_with_the_text_unchanged(language, text, code, speaker):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(method=request.method, url=str(request.url), key=request.headers.get("api-subscription-key"),
                    auth=request.headers.get("authorization"), body=json.loads(request.content))
        return audio_response()

    with TestClient(create_app(sarvam_settings()), raise_server_exceptions=False) as client:
        install_transport(client.app, handler)
        response = client.post("/tts/stream", json={"text": text, "language": language})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg" and response.content == b"ID3audio"
    assert seen["method"] == "POST" and seen["url"] == "https://api.sarvam.ai/text-to-speech/stream"
    assert seen["key"] == KEY and seen["auth"] is None
    assert seen["body"] == {
        "text": text,  # byte-for-byte: never translated, transliterated or rewritten
        "model": "bulbul:v4-flash",
        "language_code": code,
        "speaker": speaker,
        "output_audio_codec": "mp3",
        "speech_sample_rate": 24000,
        "output_audio_bitrate": "128k",
    }


def test_a_configured_speaker_can_be_requested_and_others_are_rejected():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["speaker"])
        return audio_response()

    settings = sarvam_settings(sarvam_tts_voices="ishita_enhi_companion")
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        install_transport(client.app, handler)
        ok = client.post("/tts/stream", json={"text": HINGLISH, "language": "hinglish", "voice": "ishita_enhi_companion"})
        default_alias = client.post("/tts/stream", json={"text": HINDI, "language": "hindi", "voice": "default"})
        unknown = client.post("/tts/stream", json={"text": HINDI, "language": "hindi", "voice": "aura-2-thalia-en"})
        injected = client.post("/tts/stream", json={"text": HINDI, "voice": "x\", \"model\": \"y"})
    assert ok.status_code == 200 and default_alias.status_code == 200
    assert seen == ["ishita_enhi_companion", "kavya_hi_conversational"]
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "tts_invalid_voice"
    assert injected.status_code == 422


def test_language_mapping_and_model_are_configurable():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return audio_response()

    settings = sarvam_settings(
        sarvam_tts_model="bulbul:v3", sarvam_language_hinglish="en-IN", sarvam_speaker_hinglish="shubh",
        sarvam_tts_sample_rate=16000, sarvam_tts_bitrate="64k",
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        install_transport(client.app, handler)
        assert client.post("/tts/stream", json={"text": HINGLISH, "language": "hinglish"}).status_code == 200
    assert (seen["model"], seen["language_code"], seen["speaker"]) == ("bulbul:v3", "en-IN", "shubh")
    assert (seen["speech_sample_rate"], seen["output_audio_bitrate"]) == (16000, "64k")


# ---------------------------------------------------------------- provider failures (safe errors, no leaks)

@pytest.mark.parametrize(
    "status, error",
    [
        (401, TtsAuthError), (403, TtsAuthError), (429, TtsRateLimitError), (402, TtsRateLimitError),
        (504, TtsTimeoutError), (400, TtsProviderError), (422, TtsProviderError), (500, TtsProviderError),
    ],
)
def test_http_status_maps_to_a_safe_error_and_the_body_is_never_exposed(status, error):
    provider = build_tts_provider(sarvam_settings())
    install_transport(provider, lambda r: httpx.Response(status, json={"error": {"message": f"echo {KEY} {HINDI}", "code": "x"}}))
    with pytest.raises(error) as caught:
        run(collect(provider))
    assert KEY not in caught.value.message and "echo" not in caught.value.message


def test_non_audio_and_empty_replies_are_rejected():
    provider = build_tts_provider(sarvam_settings())
    install_transport(provider, lambda r: httpx.Response(200, json={"audios": ["UklGR"]}))  # the non-streaming JSON shape
    with pytest.raises(TtsBadResponseError):
        run(collect(provider))
    with TestClient(create_app(sarvam_settings()), raise_server_exceptions=False) as client:
        install_transport(client.app, lambda r: audio_response(chunks=()))
        response = client.post("/tts/stream", json={"text": ENGLISH})
    assert response.status_code == 502 and response.json()["error"]["code"] == "tts_bad_response"


def test_network_failure_and_timeout_map_to_unavailable_and_timeout_without_leaking(caplog):
    caplog.set_level(logging.DEBUG)
    provider = build_tts_provider(sarvam_settings())

    def refuse(request):
        raise httpx.ConnectError(f"cannot reach {KEY}")

    install_transport(provider, refuse)
    with pytest.raises(TtsUnavailableError):
        run(collect(provider))

    def slow(request):
        raise httpx.ReadTimeout("slow")

    install_transport(provider, slow)
    with pytest.raises(TtsTimeoutError):
        run(collect(provider))
    assert KEY not in caplog.text and "Sarvam TTS network failure: ConnectError" in caplog.text


def test_closing_the_stream_early_closes_the_upstream_response():
    closed = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"first"
            await asyncio.Event().wait()

        async def aclose(self):
            closed.append(True)

    provider = build_tts_provider(sarvam_settings())
    install_transport(provider, lambda r: httpx.Response(200, headers={"content-type": "audio/mpeg"}, stream=Body()))

    async def scenario():
        stream = provider.stream(text=ENGLISH, voice="dev_en_conversational", language="english")
        assert await anext(stream) == b"first"
        await stream.aclose()
        assert closed == [True]

    run(scenario())


def test_logs_contain_no_text_or_key_on_success_and_failure(caplog):
    caplog.set_level(logging.DEBUG)
    with TestClient(create_app(sarvam_settings()), raise_server_exceptions=False) as client:
        install_transport(client.app, lambda r: audio_response())
        client.post("/tts/stream", json={"text": HINDI, "language": "hindi"})
        install_transport(client.app, lambda r: httpx.Response(403, json={"message": KEY}))
        client.post("/tts/stream", json={"text": HINGLISH, "language": "hinglish"})
    assert "tts stream finished" in caplog.text
    for secret in (KEY, HINDI, HINGLISH, "नमस्ते", "Namaste"):
        assert secret not in caplog.text


# ---------------------------------------------------------------- provider selection and configuration

def test_default_provider_is_deepgram_and_sarvam_is_selected_by_configuration():
    assert make_settings().tts_provider == "deepgram"
    assert build_tts_provider(make_settings(deepgram_api_key="dg")).name == "deepgram"
    assert isinstance(build_tts_provider(make_settings(deepgram_api_key="dg")), DeepgramTtsProvider)
    # a key for the OTHER provider does not make this one configured
    assert build_tts_provider(make_settings(deepgram_api_key="dg", tts_provider="sarvam")) is None
    assert build_tts_provider(make_settings(sarvam_api_key=KEY)) is None
    provider = build_tts_provider(sarvam_settings())
    assert isinstance(provider, SarvamTtsProvider) and provider.name == "sarvam" and provider.content_type == "audio/mpeg"


def test_sarvam_selected_without_key_reports_tts_not_configured_and_service_starts():
    with TestClient(create_app(make_settings(tts_provider="sarvam", deepgram_api_key="dg")), raise_server_exceptions=False) as client:
        assert client.get("/health").status_code == 200
        response = client.post("/tts/stream", json={"text": HINDI, "language": "hindi"})
    assert response.status_code == 503 and response.json()["error"]["code"] == "tts_not_configured"
    assert KEY not in response.text


def test_env_example_loads_as_is_and_describes_the_defaults(monkeypatch):
    """Copying .env.example to .env must work: env values are strings, so every setting has to parse from text."""
    for name in list(os.environ):
        if name.startswith(("TTS_", "SARVAM_", "DEEPGRAM_")):
            monkeypatch.delenv(name)
    example = Settings(_env_file=VOICEAGENT_DIR / ".env.example")
    default = Settings(_env_file=None)
    assert example.tts_provider == "deepgram" and example.sarvam_api_key is None
    for name in Settings.model_fields:
        if name.startswith(("tts_", "sarvam_", "deepgram_tts")):
            assert getattr(example, name) == getattr(default, name), f".env.example disagrees with the default of {name}"


def test_numeric_tts_settings_parse_from_environment_strings(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_TTS_BIT_RATE", "32000")
    monkeypatch.setenv("SARVAM_TTS_SAMPLE_RATE", "16000")
    settings = Settings(_env_file=None)
    assert (settings.deepgram_tts_bit_rate, settings.sarvam_tts_sample_rate) == (32000, 16000)


def test_blank_sarvam_key_in_env_means_not_configured():
    assert make_settings(sarvam_api_key="  ").sarvam_api_key is None
    assert make_settings(sarvam_api_key=KEY).sarvam_api_key.get_secret_value() == KEY
    assert KEY not in repr(make_settings(sarvam_api_key=KEY))  # masked secret


def test_allowed_voices_follow_the_selected_provider():
    assert make_settings().tts_allowed_voices == {"aura-2-thalia-en"}
    assert sarvam_settings().tts_allowed_voices == {"dev_en_conversational", "kavya_hi_conversational", "simran_enhi_customer"}
    assert "aura-2-thalia-en" not in sarvam_settings().tts_allowed_voices


@pytest.mark.parametrize(
    "overrides",
    [
        {"tts_provider": "elevenlabs"},
        {"sarvam_tts_url": "http://api.sarvam.ai/text-to-speech/stream"},
        {"sarvam_tts_model": "bulbul:v9"},
        {"sarvam_speaker_hindi": "Kavya"},
        {"sarvam_speaker_hindi": "kavya hi"},
        {"sarvam_tts_voices": "ok_voice,Bad Voice"},
        {"sarvam_language_hindi": "hindi"},
        {"sarvam_language_hinglish": "hi_IN"},
        {"sarvam_tts_sample_rate": 48000},  # REST-only: streaming accepts 8000-24000
        {"sarvam_tts_bitrate": "256k"},
    ],
)
def test_invalid_sarvam_settings_are_rejected_at_startup(overrides):
    with pytest.raises(ValidationError):
        make_settings(**overrides)


def test_the_existing_deepgram_provider_still_works_through_configuration():
    seen = {}

    def handler(request):
        seen.update(url=request.url, auth=request.headers["authorization"], body=json.loads(request.content))
        return audio_response()

    with TestClient(create_app(make_settings(deepgram_api_key="dg-key")), raise_server_exceptions=False) as client:
        install_transport(client.app, handler)
        response = client.post("/tts/stream", json={"text": HINDI, "language": "hindi"})
    assert response.status_code == 200
    assert seen["url"].params["model"] == "aura-2-thalia-en" and seen["auth"] == "Token dg-key"
    assert seen["body"] == {"text": HINDI}
