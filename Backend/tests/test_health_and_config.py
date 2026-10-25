import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.db.session import Database
from app.main import create_app
from tests.conftest import make_settings


def test_root(client):
    body = client.get("/").json()
    assert body["docs"] == "/docs"
    assert body["api"] == "/api/v1"


def test_docs_available(client):
    assert client.get("/docs").status_code == 200
    assert "/api/v1/auth/login" in client.get("/openapi.json").json()["paths"]


def test_health_is_liveness_only(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_when_database_and_auth_ok(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok", "auth": "ok"}}


def test_app_starts_with_no_database_or_secret_and_reports_it_honestly():
    app = create_app(settings=make_settings(jwt_secret=None))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200  # liveness still fine
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["checks"] == {"database": "not_configured", "auth": "not_configured"}

        # Database-backed endpoints fail gracefully, not with a stack trace.
        register = client.post("/api/v1/auth/register", json={"email": "a@example.com", "password": "password123"})
        assert register.status_code == 503
        assert register.json()["error"]["code"] == "database_unavailable"


def test_ready_reports_unreachable_database():
    unreachable = Database("postgresql+psycopg://u:p@127.0.0.1:1/none", connect_timeout_seconds=1)
    app = create_app(settings=make_settings(), database=unreachable)
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"
    assert "p@127" not in response.text  # no credentials leaked


def test_login_without_jwt_secret_is_503_not_500(database):
    app = create_app(settings=make_settings(jwt_secret=None), database=database)
    with TestClient(app) as client:
        client.post("/api/v1/auth/register", json={"email": "a@example.com", "password": "password123"})
        response = client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "password123"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_not_configured"


def test_unknown_route_uses_standard_error_shape(client):
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"


def test_unhandled_exception_hides_details(settings, database):
    app = create_app(settings=settings, database=database)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    assert response.status_code == 500
    assert "secret internal detail" not in response.text
    assert response.json()["error"]["code"] == "internal_error"


class TestSettingsValidation:
    def test_production_requires_jwt_secret(self):
        with pytest.raises(ValidationError):
            make_settings(environment="production", jwt_secret=None)

    def test_short_jwt_secret_rejected(self):
        with pytest.raises(ValidationError):
            make_settings(jwt_secret="too-short")

    def test_production_rejects_wildcard_cors(self):
        with pytest.raises(ValidationError):
            make_settings(environment="production", cors_origins="*")

    def test_database_url_is_normalised_to_psycopg3(self):
        settings = make_settings(database_url="postgresql://u:p@localhost:5432/db")
        assert settings.sqlalchemy_database_url.drivername == "postgresql+psycopg"

    def test_database_built_from_parts(self):
        settings = make_settings(postgres_host="h", postgres_user="u", postgres_password="p@ss/word", postgres_db="d")
        url = settings.sqlalchemy_database_url
        assert (url.host, url.username, url.password, url.database) == ("h", "u", "p@ss/word", "d")

    def test_no_database_by_default(self):
        assert make_settings().sqlalchemy_database_url is None

    def test_secrets_are_masked_in_repr(self):
        assert "test-only-secret" not in repr(make_settings())
