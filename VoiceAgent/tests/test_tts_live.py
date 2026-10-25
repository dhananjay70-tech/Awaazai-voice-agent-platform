"""Progressive audio delivery through a REAL local Uvicorn server (real sockets, real chunked HTTP), offline.

The TTS provider is the in-process fake, so no API key or internet is needed. The fake releases chunk 2 only after the
client has received chunk 1, which can only work if the server really streams instead of buffering.
"""

import asyncio
import threading
import time

import httpx
import pytest
import uvicorn

from app.main import create_app
from tests.conftest import make_settings
from tests.tts_fakes import FakeTTSProvider


class GatedProvider(FakeTTSProvider):
    def __init__(self):
        super().__init__([b"FIRST-CHUNK", b"SECOND-CHUNK"])
        self.release_second = threading.Event()

    async def stream(self, *, text, voice, language=None):
        self.started += 1
        self.in_flight += 1
        try:
            yield b"FIRST-CHUNK"
            while not self.release_second.is_set():
                await asyncio.sleep(0.01)
            yield b"SECOND-CHUNK"
        finally:
            self.in_flight -= 1
            self.closed += 1


@pytest.fixture
def live_server():
    provider = GatedProvider()
    app = create_app(make_settings(), tts_provider=provider)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    port = server.servers[0].sockets[0].getsockname()[1]
    yield provider, app, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


def test_audio_is_delivered_progressively_over_real_http(live_server):
    provider, app, base = live_server
    with httpx.Client(timeout=5) as client:
        with client.stream("POST", f"{base}/tts/stream", json={"text": "hello"}) as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "audio/mpeg"
            assert response.headers["transfer-encoding"] == "chunked"
            assert response.headers["x-accel-buffering"] == "no"
            assert len(response.headers["x-request-id"]) == 16
            chunks = response.iter_bytes()
            assert next(chunks) == b"FIRST-CHUNK"  # arrives while the provider is still "synthesizing"
            assert provider.in_flight == 1
            provider.release_second.set()
            assert b"".join(chunks) == b"SECOND-CHUNK"
    deadline = time.time() + 3
    while app.state.tts_service.limiter.in_use and time.time() < deadline:
        time.sleep(0.02)
    assert app.state.tts_service.limiter.in_use == 0 and provider.in_flight == 0


def test_client_closing_the_connection_releases_the_slot_over_real_http(live_server):
    provider, app, base = live_server
    with httpx.Client(timeout=5) as client:
        with client.stream("POST", f"{base}/tts/stream", json={"text": "hello"}) as response:
            assert next(response.iter_bytes()) == b"FIRST-CHUNK"
        # leaving the `with` closes the connection while the provider is still waiting: it must be cancelled
    deadline = time.time() + 5
    while (app.state.tts_service.limiter.in_use or provider.in_flight) and time.time() < deadline:
        time.sleep(0.02)
    assert app.state.tts_service.limiter.in_use == 0 and provider.in_flight == 0 and provider.closed == 1


def test_health_still_works_next_to_tts(live_server):
    _, _, base = live_server
    assert httpx.get(f"{base}/health", timeout=5).status_code == 200
