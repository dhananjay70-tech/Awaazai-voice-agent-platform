"""Security hardening: safe error logging, production docs lockdown and security headers."""

import logging

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.db.session import Database
from app.main import create_app
from app.models.user import User
from tests.conftest import make_settings

SENTINEL_HASH = "SENTINEL-HASH-must-never-be-logged"
SENTINEL_EMAIL = "sentinel-person@example.com"


def make_client(database, **settings_overrides) -> TestClient:
    app = create_app(settings=make_settings(**settings_overrides), database=database)

    @app.get("/boom-integrity")
    def boom_integrity(db: Session = Depends(get_db)):
        # Two rows with the same unique email -> IntegrityError carrying the sentinel values as SQL parameters.
        db.add(User(email=SENTINEL_EMAIL, hashed_password=SENTINEL_HASH))
        db.commit()
        db.add(User(email=SENTINEL_EMAIL, hashed_password=SENTINEL_HASH))
        db.commit()

    @app.get("/boom-plain")
    def boom_plain():
        raise RuntimeError("plain failure")

    return TestClient(app, raise_server_exceptions=False)


# --- safe error logging ---

def test_engine_hides_sql_parameters(database):
    assert database.engine.hide_parameters is True


def test_postgres_engine_also_hides_parameters():
    db = Database("postgresql+psycopg://u:p@127.0.0.1:1/none")
    assert db.engine.hide_parameters is True
    db.dispose()


def test_database_error_does_not_leak_data_to_logs_or_response(database, caplog):
    caplog.set_level(logging.DEBUG)
    with make_client(database) as client:
        response = client.get("/boom-integrity")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    everything = caplog.text + response.text
    assert SENTINEL_HASH not in everything
    assert SENTINEL_EMAIL not in everything
    assert "INSERT" not in everything  # not even the SQL text
    assert "IntegrityError" in caplog.text  # but the failure is still diagnosable
    assert response.json()["error"]["request_id"] in caplog.text  # and correlatable


def test_unexpected_error_is_still_logged_with_traceback(database, caplog):
    with make_client(database) as client:
        response = client.get("/boom-plain")
    assert response.status_code == 500
    assert "plain failure" in caplog.text and "Traceback" in caplog.text
    assert "plain failure" not in response.text


# --- production-only docs lockdown ---

@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_available_outside_production(database, path):
    with make_client(database, environment="development") as client:
        assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"])
def test_docs_disabled_in_production(database, path):
    with make_client(database, environment="production") as client:
        assert client.get(path).status_code == 404


def test_api_still_works_in_production(database):
    with make_client(database, environment="production") as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        assert client.post("/api/v1/auth/register", json={"email": "p@example.com", "password": "password123"}).status_code == 201


# --- security headers ---

BASE_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}


def assert_base_headers(response):
    for name, value in BASE_HEADERS.items():
        assert response.headers.get(name) == value, name
    assert "permissions-policy" in response.headers
    assert response.headers.get("x-request-id")


@pytest.mark.parametrize("path", ["/", "/health", "/nope", "/api/v1/users/me"])
def test_headers_on_normal_and_error_responses(database, path):
    with make_client(database) as client:
        assert_base_headers(client.get(path))


def test_headers_on_validation_errors(database):
    with make_client(database) as client:
        assert_base_headers(client.post("/api/v1/auth/register", json={}))


def test_headers_on_unhandled_500(database):
    with make_client(database) as client:
        response = client.get("/boom-plain")
    assert response.status_code == 500
    assert_base_headers(response)
    assert response.headers["x-request-id"] == response.json()["error"]["request_id"]


def test_api_responses_are_not_cacheable(database):
    with make_client(database) as client:
        assert client.get("/api/v1/users/me").headers["cache-control"] == "no-store"
        assert client.get("/health").headers.get("cache-control") != "no-store"


def test_strict_csp_on_api_but_not_on_swagger_ui(database):
    with make_client(database, environment="development") as client:
        assert client.get("/health").headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
        assert "content-security-policy" not in client.get("/docs").headers  # Swagger UI needs scripts/styles


def test_hsts_only_in_production(database):
    with make_client(database, environment="production") as client:
        assert client.get("/health").headers["strict-transport-security"] == "max-age=31536000"
    with make_client(database, environment="development") as client:
        assert "strict-transport-security" not in client.get("/health").headers


def test_cors_still_works(database):
    with make_client(database) as client:
        response = client.options(
            "/api/v1/auth/login",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
