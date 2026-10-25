"""The /health contract that the Backend's VoiceAgentClient depends on."""

import asyncio

import httpx

from app.main import create_app
from tests.conftest import make_settings


def test_health_returns_documented_response(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "status": "ok",
        "service": "awaazai-voiceagent",
        "version": "0.1.0",
        "environment": "test",
    }


def test_health_reflects_configured_service_name():
    from fastapi.testclient import TestClient

    with TestClient(create_app(make_settings(service_name="custom-name"))) as client:
        assert client.get("/health").json()["service"] == "custom-name"


def test_health_needs_no_authentication_and_leaks_no_secrets(client):
    body = client.get("/health").text.lower()
    for forbidden in ("key", "secret", "password", "token"):
        assert forbidden not in body


def test_health_is_get_only(client):
    assert client.post("/health").status_code == 405


def test_backend_client_contract():
    """Replays exactly what the Backend's client does (GET /health, JSON object, status < 400, 5 s timeout)."""
    app = create_app(make_settings())

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://voice-agent.test", timeout=5.0) as http:
            return await http.get("/health")

    response = asyncio.run(call())
    assert response.status_code < 400
    assert isinstance(response.json(), dict)
