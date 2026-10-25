import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.errors import VoiceAgentTimeoutError, VoiceAgentUnavailableError
from app.main import create_app
from app.services.voice_agent_client import VoiceAgentClient
from tests.conftest import auth_headers, make_voice_agent_client

STATUS_URL = "/api/v1/voice-agent/status"


# --- the client itself ---

def test_health_ok():
    client = make_voice_agent_client(lambda request: httpx.Response(200, json={"status": "ok"}))
    assert asyncio.run(client.health()) == {"status": "ok"}


def test_not_configured_raises_unavailable():
    with pytest.raises(VoiceAgentUnavailableError):
        asyncio.run(VoiceAgentClient(None).health())


def test_timeout_is_reported_as_timeout():
    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(VoiceAgentTimeoutError):
        asyncio.run(make_voice_agent_client(handler).health())


def test_connection_refused_is_reported_as_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(VoiceAgentUnavailableError):
        asyncio.run(make_voice_agent_client(handler).health())


def test_error_status_is_reported_as_unavailable():
    with pytest.raises(VoiceAgentUnavailableError):
        asyncio.run(make_voice_agent_client(lambda request: httpx.Response(503)).health())


def test_non_json_body_does_not_crash():
    assert asyncio.run(make_voice_agent_client(lambda request: httpx.Response(200, text="OK")).health()) == {}


# --- the API endpoint ---

def status_for(settings, database, voice_client, headers_from=None):
    app = create_app(settings=settings, database=database, voice_agent_client=voice_client)
    with TestClient(app) as http:
        headers = auth_headers(http)
        return http.get(STATUS_URL, headers=headers)


def test_status_requires_auth(client):
    assert client.get(STATUS_URL).status_code == 401


def test_status_not_configured(client):
    response = client.get(STATUS_URL, headers=auth_headers(client))
    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"
    assert response.json()["configured"] is False


def test_status_ok(settings, database):
    voice = make_voice_agent_client(lambda request: httpx.Response(200, json={}))
    response = status_for(settings, database, voice)
    assert response.json() == {"configured": True, "status": "ok", "detail": None}


def test_status_unavailable(settings, database):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    response = status_for(settings, database, make_voice_agent_client(handler))
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"


def test_status_timeout(settings, database):
    def handler(request):
        raise httpx.ConnectTimeout("slow", request=request)

    response = status_for(settings, database, make_voice_agent_client(handler))
    assert response.json()["status"] == "timeout"
