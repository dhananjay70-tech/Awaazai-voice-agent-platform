import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from tests.conftest import make_settings


def test_defaults_are_safe():
    settings = Settings(_env_file=None)
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.service_name == "awaazai-voiceagent"
    assert not settings.is_production


@pytest.mark.parametrize("value", ["staging", "prod", "", "PRODUCTION "])
def test_invalid_environment_rejected(value):
    with pytest.raises(ValidationError):
        make_settings(environment=value)


@pytest.mark.parametrize("value", ["VERBOSE", "trace", ""])
def test_invalid_log_level_rejected(value):
    with pytest.raises(ValidationError):
        make_settings(log_level=value)


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    settings = Settings(_env_file=None)
    assert settings.is_production and settings.log_level == "ERROR"


def test_unknown_env_vars_are_ignored(monkeypatch):
    monkeypatch.setenv("SOME_UNRELATED_VARIABLE", "x")
    Settings(_env_file=None)  # must not raise


def test_docs_available_outside_production():
    with TestClient(create_app(make_settings(environment="development"))) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"])
def test_docs_disabled_in_production(path):
    with TestClient(create_app(make_settings(environment="production"))) as client:
        assert client.get(path).status_code == 404
        assert client.get("/health").status_code == 200  # the service itself still works
