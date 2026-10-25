"""Structured errors, request ids, security headers and safe logging."""

import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.errors import AppError
from app.main import create_app
from tests.conftest import make_settings

SENSITIVE = "SENSITIVE-user-speech-or-key-12345"


class Payload(BaseModel):
    text: str


class TeapotError(AppError):
    status_code = 418
    code = "teapot"
    message = "I am a teapot"


@pytest.fixture
def app_with_test_routes(settings):
    app = create_app(settings=settings)

    @app.get("/boom")
    def boom():
        raise RuntimeError(SENSITIVE)

    @app.get("/teapot")
    def teapot():
        raise TeapotError(details={"hint": "short and stout"})

    @app.post("/echo")
    def echo(payload: Payload):
        return payload

    return app


@pytest.fixture
def test_client(app_with_test_routes):
    with TestClient(app_with_test_routes, raise_server_exceptions=False) as client:
        yield client


# ---- error shape ----

def test_unknown_route_uses_standard_error_shape(client):
    response = client.get("/nope")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "http_404"
    assert error["request_id"] == response.headers["x-request-id"]


def test_app_error_is_rendered(test_client):
    response = test_client.get("/teapot")
    assert response.status_code == 418
    assert response.json()["error"]["code"] == "teapot"
    assert response.json()["error"]["details"] == {"hint": "short and stout"}


def test_validation_error_does_not_echo_submitted_values(test_client):
    response = test_client.post("/echo", json={"text": 12345, "extra": SENSITIVE})
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"][0]["field"] == "text"
    assert "12345" not in response.text and SENSITIVE not in response.text


def test_unhandled_error_is_generic_in_response_and_logged_with_traceback(test_client, caplog):
    with caplog.at_level(logging.ERROR):
        response = test_client.get("/boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert SENSITIVE not in response.text  # nothing internal reaches the client
    assert "Traceback" in caplog.text  # but operators can still diagnose it
    assert response.json()["error"]["request_id"] in caplog.text


# ---- request ids ----

def test_request_id_header_present_and_unique(client):
    first = client.get("/health").headers["x-request-id"]
    second = client.get("/health").headers["x-request-id"]
    assert first and second and first != second


def test_client_supplied_request_id_is_ignored(client):
    response = client.get("/health", headers={"X-Request-ID": "forged\nfake log line"})
    assert response.headers["x-request-id"] != "forged\nfake log line"
    assert len(response.headers["x-request-id"]) == 16


def test_request_is_logged_without_query_string_or_body(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.request"):
        client.get("/health?token=SENSITIVE-in-query")
    assert "GET /health -> 200" in caplog.text
    assert "SENSITIVE" not in caplog.text


# ---- security headers ----

EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
}


@pytest.mark.parametrize("path", ["/health", "/nope"])
def test_security_headers_on_success_and_error(client, path):
    response = client.get(path)
    for name, value in EXPECTED.items():
        assert response.headers.get(name) == value, name


def test_security_headers_on_unhandled_500(test_client):
    response = test_client.get("/boom")
    assert response.status_code == 500
    for name, value in EXPECTED.items():
        assert response.headers.get(name) == value, name
    assert response.headers["x-request-id"] == response.json()["error"]["request_id"]


def test_swagger_ui_is_exempt_from_strict_csp_in_development(client):
    assert "content-security-policy" not in client.get("/docs").headers
    assert "content-security-policy" in client.get("/health").headers
