"""Test fixtures: an isolated app with an in-memory SQLite database and a fake JWT secret.

Nothing here touches a real database, a real .env file or real API keys.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.base import Base
from app.db.session import Database
from app.main import create_app
from app.services.voice_agent_client import VoiceAgentClient

TEST_JWT_SECRET = "test-only-secret-not-for-real-use-0123456789"


def make_settings(**overrides) -> Settings:
    values = {"environment": "test", "jwt_secret": TEST_JWT_SECRET, "log_level": "WARNING"}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # _env_file=None: ignore any developer .env


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def database() -> Database:
    db = Database("sqlite+pysqlite://")
    Base.metadata.create_all(db.engine)
    yield db
    db.dispose()


@pytest.fixture
def client(settings, database) -> TestClient:
    app = create_app(settings=settings, database=database)
    with TestClient(app) as test_client:
        yield test_client


def make_voice_agent_client(handler, base_url="http://voice-agent.test") -> VoiceAgentClient:
    return VoiceAgentClient(base_url, timeout_seconds=1.0, transport=httpx.MockTransport(handler))


# --- helpers used by several test modules ---

def register(client: TestClient, email="alice@example.com", password="correct-horse-battery"):
    return client.post("/api/v1/auth/register", json={"email": email, "password": password})


def auth_headers(client: TestClient, email="alice@example.com", password="correct-horse-battery") -> dict:
    register(client, email, password)
    token = client.post("/api/v1/auth/login", json={"email": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


AGENT_PAYLOAD = {
    "name": "Support Bot",
    "description": "Answers support calls",
    "system_prompt": "You are a helpful support agent.",
    "language": "hi-IN",
    "voice_config": {"provider": "example", "voice_id": "v1", "speed": 1.2},
}
