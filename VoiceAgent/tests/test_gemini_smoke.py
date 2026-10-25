"""OPTIONAL real-Gemini smoke test. It makes ONE tiny, real (billable) API call.

Skipped by default. It runs only when BOTH are true:
  1. the environment variable RUN_GEMINI_SMOKE=1 is set explicitly, and
  2. GEMINI_API_KEY is configured (in the environment or VoiceAgent/.env).

It never prints the key, the prompt or the reply: assertions only report lengths and booleans.

    $env:RUN_GEMINI_SMOKE = "1"; python -m pytest tests/test_gemini_smoke.py -v
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

settings = Settings()  # reads the real environment and VoiceAgent/.env (this is the only test that does)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_GEMINI_SMOKE") != "1" or settings.gemini_api_key is None,
    reason="real-Gemini smoke test: set RUN_GEMINI_SMOKE=1 and configure GEMINI_API_KEY to run",
)


def test_real_gemini_round_trip_with_history():
    real_settings = Settings(environment="test", log_level="WARNING")
    with TestClient(create_app(real_settings)) as client:
        first = client.post(
            "/chat",
            json={"message": "Namaste! Introduce yourself in one short sentence.", "session_id": "smoke-test", "language": "hinglish"},
        )
        assert first.status_code == 200, f"unexpected status {first.status_code}, code={first.json().get('error', {}).get('code')}"
        body = first.json()
        assert body["model"] == real_settings.gemini_model
        assert isinstance(body["reply"], str) and body["reply"].strip()
        assert body["session_id"] == "smoke-test"

        # Second turn proves history reaches the model: ask it to recall something we just told it.
        client.post("/chat", json={"message": "Remember this code word: kesar.", "session_id": "smoke-test", "language": "english"})
        recall = client.post("/chat", json={"message": "What was the code word I told you?", "session_id": "smoke-test", "language": "english"})
        assert recall.status_code == 200
        assert "kesar" in recall.json()["reply"].lower()
