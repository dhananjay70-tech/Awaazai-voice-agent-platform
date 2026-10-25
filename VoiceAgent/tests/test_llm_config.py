"""Phase 2 configuration: defaults, validation, secret handling, provider selection."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import VOICEAGENT_DIR, Settings
from app.llm.gemini import GeminiProvider
from app.main import build_provider
from tests.conftest import make_settings

FAKE_KEY = "fake-test-key-NOT-A-REAL-KEY-0123456789"


def test_defaults():
    settings = Settings(_env_file=None, gemini_api_key=None)
    assert settings.llm_provider == "gemini"
    assert settings.gemini_model == "gemini-2.5-flash"
    assert settings.gemini_api_key is None
    assert 0 < settings.llm_timeout_seconds <= 120
    assert settings.session_max_sessions >= 1 and settings.session_ttl_seconds > 0
    assert settings.session_max_turns >= 1 and settings.session_max_history_chars >= 500


def test_key_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    settings = Settings(_env_file=None)
    assert settings.gemini_api_key.get_secret_value() == FAKE_KEY


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_key_counts_as_missing(monkeypatch, blank):
    monkeypatch.setenv("GEMINI_API_KEY", blank)
    assert Settings(_env_file=None).gemini_api_key is None


def test_key_is_masked_everywhere_settings_are_printed():
    settings = make_settings(gemini_api_key=FAKE_KEY)
    for rendering in (repr(settings), str(settings), settings.model_dump_json(), str(settings.model_dump())):
        assert FAKE_KEY not in rendering
        assert "NOT-A-REAL-KEY" not in rendering


def test_env_overrides_for_model_and_limits(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("SESSION_MAX_TURNS", "5")
    settings = Settings(_env_file=None, gemini_api_key=None)
    assert (settings.gemini_model, settings.llm_timeout_seconds, settings.session_max_turns) == ("gemini-2.5-flash-lite", 7.5, 5)


@pytest.mark.parametrize(
    "override",
    [
        {"llm_provider": "openai"},
        {"llm_timeout_seconds": 0},
        {"llm_timeout_seconds": 500},
        {"llm_temperature": 3},
        {"llm_temperature": -0.1},
        {"llm_max_output_tokens": 0},
        {"llm_max_output_tokens": 100_000},
        {"session_max_sessions": 0},
        {"session_ttl_seconds": 0},
        {"session_max_turns": 0},
        {"session_max_history_chars": 10},
        {"session_lock_timeout_seconds": 0},
    ],
)
def test_invalid_values_are_rejected_at_startup(override):
    with pytest.raises(ValidationError):
        make_settings(**override)


def test_no_provider_without_a_key_and_no_network_needed():
    assert build_provider(make_settings(gemini_api_key=None)) is None


def test_provider_is_built_from_settings_when_key_present():
    provider = build_provider(make_settings(gemini_api_key=FAKE_KEY, gemini_model="gemini-2.5-flash"))
    assert isinstance(provider, GeminiProvider)
    assert provider.model == "gemini-2.5-flash"


# ---------------------------------------------------------------- repository hygiene

def test_env_example_documents_the_variables_without_a_real_secret():
    text = (VOICEAGENT_DIR / ".env.example").read_text(encoding="utf-8")
    assert "GEMINI_API_KEY" in text
    assert "GEMINI_MODEL" in text
    assert not re.search(r"AIza[0-9A-Za-z_\-]{20,}", text), ".env.example must never contain a real-looking key"
    for line in text.splitlines():
        if line.startswith("GEMINI_API_KEY="):
            assert line.split("=", 1)[1].split("#")[0].strip() == "", "the example key must be empty"


def test_gitignore_excludes_secret_files():
    patterns = (VOICEAGENT_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in patterns and ".env.*" in patterns and "!.env.example" in patterns


def test_no_real_looking_key_in_source_or_tests():
    pattern = re.compile(r"AIza[0-9A-Za-z_\-]{30,}")
    offenders = [
        str(path.relative_to(VOICEAGENT_DIR))
        for folder in ("app", "tests")
        for path in (VOICEAGENT_DIR / folder).rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
