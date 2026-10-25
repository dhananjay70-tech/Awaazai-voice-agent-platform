"""WS /voice/stream through a REAL local Uvicorn server and a real WebSocket client (real sockets, offline).

STT, Gemini and TTS are the in-process fakes, so no key or internet is needed. The Gemini fake releases its second
sentence only after the client has received the first sentence's audio over the socket, which can only work if the
server really streams instead of buffering the turn.
"""

import asyncio
import json
import threading
import time

import pytest
import uvicorn
from websockets.asyncio.client import connect

from app.main import create_app
from tests.conftest import FakeProvider, make_settings
from tests.stt_fakes import FakeSTTProvider, final
from tests.tts_fakes import FakeTTSProvider

CHUNK = b"\x01\x00" * 160


class HeldGate:
    """An asyncio.Event that a thread can open (the test client runs in a different thread/loop than the server)."""

    def __init__(self):
        self._open = threading.Event()

    async def wait(self):
        while not self._open.is_set():
            await asyncio.sleep(0.01)

    def set(self):
        self._open.set()


@pytest.fixture
def live_server():
    gate = HeldGate()
    llm = FakeProvider(chunks=["Pehla vaakya. ", "Doosra vaakya."], chunk_gates=[HeldGate(), gate])
    llm.chunk_gates[0].set()
    tts = FakeTTSProvider([b"MP3-", b"BYTES"])
    stt = FakeSTTProvider(on_finish=[final("namaste")])
    app = create_app(make_settings(), llm_provider=llm, stt_provider=stt, tts_provider=tts)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical", ws="websockets-sansio"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    port = server.servers[0].sockets[0].getsockname()[1]
    yield app, llm, tts, gate, f"ws://127.0.0.1:{port}/voice/stream"
    server.should_exit = True
    thread.join(5)


def test_text_turn_over_real_sockets_streams_audio_before_gemini_finishes(live_server):
    app, llm, tts, gate, url = live_server

    async def scenario():
        async with connect(url, max_size=2**20) as ws:
            await ws.send(json.dumps({"type": "config", "language": "hinglish"}))
            await ws.send(json.dumps({"type": "text", "text": "Namaste"}))
            received: list = []
            while True:
                message = await asyncio.wait_for(ws.recv(), 10)
                received.append(message)
                if isinstance(message, str) and json.loads(message)["type"] == "audio_end":
                    break
            # sentence 1 was heard while Gemini still withholds sentence 2
            assert not any(isinstance(m, str) and json.loads(m)["type"] == "done" for m in received)
            assert [m for m in received if isinstance(m, bytes)] == [b"MP3-", b"BYTES"]
            gate.set()
            async for message in ws:
                received.append(message)
            return received

    received = asyncio.run(asyncio.wait_for(scenario(), 30))
    events = [json.loads(m) for m in received if isinstance(m, str)]
    assert events[0]["type"] == "ready" and events[-1]["type"] == "done"
    assert events[-1]["sentences"] == 2 and events[-1]["audio_complete"] is True
    assert [m for m in received if isinstance(m, bytes)] == [b"MP3-", b"BYTES"] * 2
    deadline = time.time() + 3
    while time.time() < deadline and app.state.voice_service.limiter.in_use:
        time.sleep(0.02)
    assert app.state.voice_service.limiter.in_use == 0 and app.state.chat_service.limiter.in_use == 0
    assert app.state.tts_service.limiter.in_use == 0


def test_audio_turn_over_real_sockets_and_health_still_works(live_server):
    app, llm, tts, gate, url = live_server
    gate.set()

    async def scenario():
        async with connect(url, max_size=2**20) as ws:
            await ws.send(json.dumps({"type": "config", "language": "hindi", "sample_rate": 16000}))
            for _ in range(3):
                await ws.send(CHUNK)  # raw PCM16 frames, no WAV header
            await ws.send(json.dumps({"type": "end"}))
            return [m async for m in ws]

    received = asyncio.run(asyncio.wait_for(scenario(), 30))
    events = [json.loads(m) for m in received if isinstance(m, str)]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "ready" and "final" in kinds and kinds[-1] == "done"
    assert llm.calls[0][1][-1].text == "namaste"

    import httpx

    assert httpx.get(url.replace("ws://", "http://").replace("/voice/stream", "/health"), timeout=5).status_code == 200
