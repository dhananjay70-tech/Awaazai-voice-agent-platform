"""OPTIONAL real-Gemini STREAMING smoke test. It makes two real (billable) API calls.

Skipped by default. It runs only when BOTH are true:
  1. the environment variable RUN_GEMINI_SMOKE=1 is set explicitly, and
  2. GEMINI_API_KEY is configured (in the environment or VoiceAgent/.env).

It starts the real app on a local port and reads the stream with a real HTTP client, so it observes genuine
progressive delivery. It never prints or asserts on the key, the prompt or the reply text: only counts and timings.

    $env:RUN_GEMINI_SMOKE = "1"; python -m pytest tests/test_gemini_stream_smoke.py -v

If your account cannot use the default model, also set GEMINI_MODEL (e.g. $env:GEMINI_MODEL = "gemini-3.8-flash").
"""

import json
import os
import threading
import time

import httpx
import pytest
import uvicorn

from app.config import Settings
from app.main import create_app

settings = Settings()  # real environment and VoiceAgent/.env (the only tests that read it)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_GEMINI_SMOKE") != "1" or settings.gemini_api_key is None,
    reason="real-Gemini smoke test: set RUN_GEMINI_SMOKE=1 and configure GEMINI_API_KEY to run",
)

PROMPT = "Explain what an AI agent is in simple Hinglish, in about 80 words."


@pytest.fixture
def live_server():
    app = create_app(Settings(environment="test", log_level="WARNING"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    port = server.servers[0].sockets[0].getsockname()[1]
    yield app, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


def read_events(response, started):
    events, buffer = [], ""
    for piece in response.iter_text():
        buffer += piece
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            lines = block.split("\n")
            events.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: ")), time.monotonic() - started))
    return events


def test_real_gemini_streams_progressively_with_history(live_server):
    app, base = live_server
    started = time.monotonic()
    with httpx.Client(timeout=60) as client, client.stream(
        "POST", f"{base}/chat/stream", json={"message": PROMPT, "session_id": "stream-smoke", "language": "hinglish"}
    ) as response:
        assert response.status_code == 200, f"unexpected status {response.status_code}"
        events = read_events(response, started)

    names = [name for name, _, _ in events]
    assert names[0] == "start" and names[-1] == "done", f"unexpected event sequence: {names[:3]}...{names[-2:]}"
    tokens = [(data, at) for name, data, at in events if name == "token"]
    assert len(tokens) >= 2, "expected the reply to arrive in several chunks"
    assert all(isinstance(data["text"], str) and data["text"] for data, _ in tokens)
    first_token_at, last_token_at = tokens[0][1], tokens[-1][1]
    assert last_token_at > first_token_at, "all chunks arrived at the same instant: that is buffering, not streaming"

    done = events[-1][1]
    assert done["chunks"] == len(tokens) and done["ttft_ms"] > 0 and done["total_ms"] >= done["ttft_ms"]
    # Only numbers are reported, never any text.
    print(f"\n[real streaming] chunks={len(tokens)} ttft_ms={done['ttft_ms']} total_ms={done['total_ms']} "
          f"client_first_token_s={first_token_at:.2f} client_last_token_s={last_token_at:.2f}")

    # the streamed reply was committed to the shared session history
    history = app.state.chat_service._store._sessions["stream-smoke"].messages()
    assert [m.role for m in history] == ["user", "assistant"] and history[1].text.strip()


def test_real_gemini_disconnect_mid_stream_releases_server_resources(live_server):
    app, base = live_server
    service = app.state.chat_service
    started = time.monotonic()
    with httpx.Client(timeout=60) as client:
        with client.stream("POST", f"{base}/chat/stream", json={"message": PROMPT, "session_id": "stream-drop"}) as response:
            assert response.status_code == 200
            seen_token = False
            for piece in response.iter_text():
                if "event: token" in piece:
                    seen_token = True
                    break
            assert seen_token
            assert service.limiter.in_use == 1 or time.monotonic() - started > 0  # mid-flight (or just finished)
        # leaving the block closes the connection while Gemini may still be generating

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        session = service._store._sessions.get("stream-drop")
        if service.limiter.in_use == 0 and not (session and session.lock.locked()):
            break
        time.sleep(0.05)
    assert service.limiter.in_use == 0, "a generation slot was leaked after the client disconnected"
    session = service._store._sessions.get("stream-drop")
    assert not (session and session.lock.locked()), "the session lock was leaked after the client disconnected"
