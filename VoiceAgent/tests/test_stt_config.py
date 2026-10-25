"""Phase 3B configuration: defaults, validation, secret handling, provider selection, repository hygiene."""

import re

import pytest
from pydantic import ValidationError

from app.config import VOICEAGENT_DIR, Settings
from app.main import build_stt_provider
from app.stt.deepgram import DeepgramProvider
from tests.conftest import make_settings

FAKE_KEY = "fake-deepgram-key-NOT-A-REAL-KEY-0123456789"


def test_defaults_are_safe_and_documented():
    s = make_settings()
    assert s.stt_provider == "deepgram" and s.deepgram_model == "nova-3"
    assert s.deepgram_url.startswith("wss://")
    assert (s.deepgram_language_english, s.deepgram_language_hindi, s.deepgram_language_hinglish) == ("en", "hi", "multi")
    assert s.stt_idle_timeout_seconds < 10  # Deepgram closes after ~10 s without audio
    assert s.stt_max_chunk_bytes == 32768 and s.stt_max_concurrent_streams >= 1
    assert s.deepgram_api_key is None


def test_key_read_from_environment_and_masked(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", FAKE_KEY)
    s = Settings(_env_file=None)
    assert s.deepgram_api_key.get_secret_value() == FAKE_KEY
    for rendering in (repr(s), str(s), s.model_dump_json(), str(s.model_dump())):
        assert FAKE_KEY not in rendering and "NOT-A-REAL-KEY" not in rendering


@pytest.mark.parametrize("blank", ["", "  "])
def test_blank_key_counts_as_missing(monkeypatch, blank):
    monkeypatch.setenv("DEEPGRAM_API_KEY", blank)
    assert Settings(_env_file=None).deepgram_api_key is None


@pytest.mark.parametrize("url", ["http://api.deepgram.com/v1/listen", "ws://api.deepgram.com/v1/listen", "ftp://x", "api.deepgram.com"])
def test_insecure_or_invalid_provider_urls_are_rejected(url):
    with pytest.raises(ValidationError):
        make_settings(deepgram_url=url)  # the API key travels in a header: never over cleartext to a remote host


@pytest.mark.parametrize("url", ["wss://api.deepgram.com/v1/listen", "ws://127.0.0.1:9/v1/listen", "ws://localhost:9/v1/listen"])
def test_secure_or_local_provider_urls_are_accepted(url):
    assert make_settings(deepgram_url=url).deepgram_url == url


@pytest.mark.parametrize(
    "override",
    [
        {"stt_idle_timeout_seconds": 0}, {"stt_idle_timeout_seconds": 10},  # must be below Deepgram's own 10 s
        {"stt_connect_timeout_seconds": 0}, {"stt_finish_timeout_seconds": 0}, {"stt_send_timeout_seconds": 0},
        {"stt_max_stream_seconds": 0}, {"stt_max_audio_seconds": 0}, {"stt_max_audio_seconds": 4000},
        {"stt_max_chunk_bytes": 10}, {"stt_max_chunk_bytes": 10_000_000},
        {"stt_max_concurrent_streams": 0}, {"deepgram_endpointing_ms": 5}, {"stt_provider": "other"},
    ],
)
def test_invalid_values_are_rejected_at_startup(override):
    with pytest.raises(ValidationError):
        make_settings(**override)


def test_wildcard_origin_rejected_in_production_only():
    make_settings(environment="development", stt_allowed_origins="*")
    with pytest.raises(ValidationError):
        make_settings(environment="production", stt_allowed_origins="*")


def test_origin_list_parsing():
    s = make_settings(stt_allowed_origins=" http://a.test , http://b.test ,, ")
    assert s.stt_origin_list == ["http://a.test", "http://b.test"]


def test_no_provider_without_a_key_and_provider_built_when_present():
    assert build_stt_provider(make_settings()) is None
    provider = build_stt_provider(make_settings(deepgram_api_key=FAKE_KEY, deepgram_language_hinglish="hi"))
    assert isinstance(provider, DeepgramProvider)
    assert provider.model == "nova-3"
    assert (provider.language_code("english"), provider.language_code("hindi"), provider.language_code("hinglish")) == ("en", "hi", "hi")


def test_env_example_documents_stt_variables_without_a_real_secret():
    text = (VOICEAGENT_DIR / ".env.example").read_text(encoding="utf-8")
    for name in ("DEEPGRAM_API_KEY", "DEEPGRAM_MODEL", "DEEPGRAM_LANGUAGE_HINGLISH", "STT_IDLE_TIMEOUT_SECONDS",
                 "STT_MAX_AUDIO_SECONDS", "STT_MAX_CONCURRENT_STREAMS", "STT_ALLOWED_ORIGINS"):
        assert name in text, name
    for line in text.splitlines():
        if line.startswith("DEEPGRAM_API_KEY="):
            assert line.split("=", 1)[1].split("#")[0].strip() == "", "the example key must be empty"
    assert not re.search(r"\b[0-9a-f]{40}\b", text), "no real-looking Deepgram key in .env.example"
