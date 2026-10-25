"""End to end over REAL sockets, with no mocks between the pieces:

    real websockets client -> real uvicorn -> real app + real DeepgramProvider -> fake Deepgram (real websockets server)

The only fake is Deepgram itself (localhost, no key, no internet). This verifies the whole wiring: handshake headers,
origin checks, progressive delivery, protocol messages sent upstream, and that a client disconnect or a failure
closes the upstream connection.
"""

import asyncio
import json
import logging
import threading
import time

import pytest
import uvicorn
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from app.logging_setup import configure_logging
from app.main import create_app
from tests.conftest import make_settings
from tests.fake_deepgram import FakeDeepgramServer, results

KEY = "fake-deepgram-key-NOT-A-REAL-KEY-0123456789"
CHUNK = b"\x01\x00" * 160
CONFIG = {"type": "config", "encoding": "linear16", "sample_rate": 16000, "channels": 1, "language": "hinglish"}


class LiveApp:
    """The real app served by a real uvicorn in a background thread."""

    def __init__(self, deepgram: FakeDeepgramServer, ws_impl: str = "websockets-sansio", **settings):
        values = dict(deepgram_api_key=KEY, deepgram_url=deepgram.url, log_level="WARNING", stt_connect_timeout_seconds=3)
        values.update(settings)
        self.app = create_app(make_settings(**values))
        self._server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=0, log_level="critical", ws=ws_impl))
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self):
        self._thread.start()
        for _ in range(100):
            if self._server.started:
                break
            time.sleep(0.05)
        assert self._server.started
        self.port = self._server.servers[0].sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{self.port}/stt/stream"
        return self

    def __exit__(self, *exc):
        self._server.should_exit = True
        self._thread.join(5)

    @property
    def limiter(self):
        return self.app.state.stt_service.limiter


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 30))


async def recv_json(ws, timeout=5):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def drain(ws):
    """Everything the server sends until it closes the connection."""
    events = []
    try:
        while True:
            events.append(await recv_json(ws))
    except ConnectionClosed:
        return events


def names(events):
    return [e["type"] for e in events]


# ---------------------------------------------------------------- the happy path

@pytest.mark.parametrize("ws_impl", ["websockets", "websockets-sansio"])  # uvicorn's default (legacy) and its newer one
def test_full_chain_transcribes_and_follows_the_documented_upstream_protocol(ws_impl):
    script = {
        1: [results("namaste")],
        2: [results("namaste duniya", is_final=True, speech_final=True, start=0.0, duration=1.1)],
    }
    with FakeDeepgramServer(on_audio=script, on_close_stream=[results("kaise ho", is_final=True, start=1.1)]) as deepgram, \
            LiveApp(deepgram, ws_impl=ws_impl) as live:
        async def scenario():
            async with connect(live.url) as ws:
                await ws.send(json.dumps(CONFIG))
                ready = await recv_json(ws)
                await ws.send(CHUNK)
                partial = await recv_json(ws)
                await ws.send(CHUNK)
                final1 = await recv_json(ws)
                await ws.send(json.dumps({"type": "end"}))
                rest = await drain(ws)
                return ready, partial, final1, rest, ws.response.headers

        ready, partial, final1, rest, headers = run(scenario())

    assert ready["type"] == "ready" and ready["language"] == "hinglish" and ready["model"] == "nova-3"
    assert (partial["type"], partial["text"]) == ("partial", "namaste")
    assert (final1["type"], final1["text"], final1["speech_final"]) == ("final", "namaste duniya", True)
    assert names(rest) == ["final", "done"] and rest[0]["text"] == "kaise ho" and rest[1]["finals"] == 2
    assert len(headers["x-request-id"]) == 16 and headers["x-content-type-options"] == "nosniff"

    # what our server sent to Deepgram, as Deepgram saw it
    handshake = deepgram.handshakes[0]
    assert handshake["authorization"] == f"Token {KEY}"
    assert handshake["query"]["language"] == "multi" and handshake["query"]["sample_rate"] == "16000"
    assert handshake["query"]["encoding"] == "linear16" and handshake["query"]["interim_results"] == "true"
    assert deepgram.audio_frames == [CHUNK, CHUNK]  # the audio arrived unchanged
    assert deepgram.control_messages == [{"type": "Finalize"}, {"type": "CloseStream"}]
    assert deepgram.client_gone.wait(3)


def test_transcripts_arrive_incrementally_while_the_client_is_still_speaking():
    with FakeDeepgramServer(on_audio={1: [results("first words")], 3: [results("first words second words")]}) as deepgram, \
            LiveApp(deepgram) as live:
        async def scenario():
            async with connect(live.url) as ws:
                await ws.send(json.dumps(CONFIG))
                await recv_json(ws)
                await ws.send(CHUNK)
                started = time.monotonic()
                first = await recv_json(ws)  # delivered right away, before any further audio is sent
                latency = time.monotonic() - started
                await ws.send(CHUNK)
                await ws.send(CHUNK)
                second = await recv_json(ws)
                return first, second, latency

        first, second, latency = run(scenario())
    assert first["text"] == "first words" and second["text"] == "first words second words"
    assert latency < 1.0


@pytest.mark.parametrize("language,code", [("english", "en"), ("hindi", "hi"), ("hinglish", "multi")])
def test_requested_language_reaches_deepgram_as_the_configured_code(language, code):
    with FakeDeepgramServer() as deepgram, LiveApp(deepgram) as live:
        async def scenario():
            async with connect(live.url) as ws:
                await ws.send(json.dumps({**CONFIG, "language": language}))
                await recv_json(ws)
                await ws.send(json.dumps({"type": "end"}))
                await drain(ws)

        run(scenario())
    assert deepgram.handshakes[0]["query"]["language"] == code


# ---------------------------------------------------------------- cancellation reaches the provider connection

def test_client_disconnect_closes_the_upstream_deepgram_connection():
    with FakeDeepgramServer(on_audio={1: [results("hello")]}) as deepgram, LiveApp(deepgram) as live:
        async def scenario():
            async with connect(live.url) as ws:
                await ws.send(json.dumps(CONFIG))
                await recv_json(ws)
                await ws.send(CHUNK)
                await recv_json(ws)  # the stream is live and transcribing
                assert live.limiter.in_use == 1
            # leaving the block closes the client connection abruptly (no "end" message)

        run(scenario())
        assert deepgram.client_gone.wait(5), "the upstream Deepgram connection was NOT closed after the client left"
        assert deepgram.control_messages == []  # a cancelled stream is dropped, not "finalized"
        deadline = time.monotonic() + 5
        while live.limiter.in_use and time.monotonic() < deadline:
            time.sleep(0.02)
        assert live.limiter.in_use == 0


def test_idle_client_is_dropped_and_upstream_is_closed():
    with FakeDeepgramServer() as deepgram, LiveApp(deepgram, stt_idle_timeout_seconds=0.3) as live:
        async def scenario():
            async with connect(live.url) as ws:
                await ws.send(json.dumps(CONFIG))
                await recv_json(ws)
                events = await drain(ws)  # the client says nothing more
                return events, ws.close_code

        events, close_code = run(scenario())
        assert events[-1]["code"] == "stt_idle_timeout" and close_code == 1008
        assert deepgram.client_gone.wait(5)


# ---------------------------------------------------------------- provider failures seen by a real client

def test_deepgram_rejecting_the_key_gives_a_safe_error_without_leaking_the_key():
    with FakeDeepgramServer(reject_status=401) as deepgram, LiveApp(deepgram) as live:
        async def scenario():
            async with connect(live.url) as ws:
                await ws.send(json.dumps(CONFIG))
                return await drain(ws), ws.close_code

        events, close_code = run(scenario())
    assert names(events) == ["error"] and events[0]["code"] == "stt_authentication_failed" and close_code == 1011
    assert KEY not in json.dumps(events)


@pytest.mark.parametrize("code,error", [(1008, "stt_invalid_audio"), (1011, "stt_provider_error")])
def test_deepgram_closing_mid_stream_is_reported_with_a_safe_code(code, error):
    with FakeDeepgramServer(on_audio={1: [results("heard something")]}, close_after_audio=(1, code)) as deepgram, LiveApp(deepgram) as live:
        async def scenario():
            async with connect(live.url) as ws:
                await ws.send(json.dumps(CONFIG))
                await recv_json(ws)
                await ws.send(CHUNK)
                return await drain(ws)

        events = run(scenario())
    assert names(events) == ["partial", "error"] and events[-1]["code"] == error


def test_deepgram_unreachable_is_unavailable():
    with FakeDeepgramServer() as deepgram:
        url = deepgram.url
    # the fake is stopped now: its port refuses connections
    dead = FakeDeepgramServer()
    dead.port = int(url.rsplit(":", 1)[1].split("/")[0])

    class Closed:  # a Deepgram URL that nothing listens on
        url = f"ws://127.0.0.1:{dead.port}/v1/listen"

    with LiveApp(Closed()) as live:
        async def scenario():
            async with connect(live.url) as ws:
                await ws.send(json.dumps(CONFIG))
                return await drain(ws)

        events = run(scenario())
    assert events[-1]["code"] == "stt_unavailable"


# ---------------------------------------------------------------- browser security and limits over real sockets

def test_browser_origin_not_on_the_allow_list_is_refused_at_the_handshake():
    with FakeDeepgramServer() as deepgram, LiveApp(deepgram) as live:
        async def attempt(origin):
            try:
                async with connect(live.url, origin=origin) as ws:
                    await ws.send(json.dumps(CONFIG))
                    ready = await recv_json(ws)
                    await ws.send(json.dumps({"type": "end"}))
                    await drain(ws)
                    return ready["type"]
            except InvalidStatus as exc:
                return exc.response.status_code

        assert run(attempt("http://evil.example")) == 403  # refused before any WebSocket exists
        assert run(attempt("http://localhost:5173")) == "ready"
        assert deepgram.connections == 1  # only the allowed origin ever reached Deepgram


def test_total_audio_limit_is_enforced_over_real_sockets():
    with FakeDeepgramServer() as deepgram, LiveApp(deepgram, stt_max_audio_seconds=0.05) as live:
        async def scenario():
            async with connect(live.url) as ws:
                await ws.send(json.dumps(CONFIG))
                await recv_json(ws)
                for _ in range(10):
                    try:
                        await ws.send(CHUNK)
                    except ConnectionClosed:
                        break
                return await drain(ws), ws.close_code

        events, close_code = run(scenario())
        assert events[-1]["code"] == "stt_limit_exceeded" and close_code == 1009
        assert deepgram.client_gone.wait(5)
        assert len(deepgram.audio_frames) < 10


def test_concurrent_stream_limit_over_real_sockets():
    with FakeDeepgramServer() as deepgram, LiveApp(deepgram, stt_max_concurrent_streams=1) as live:
        async def scenario():
            async with connect(live.url) as first:
                await first.send(json.dumps(CONFIG))
                await recv_json(first)
                async with connect(live.url) as second:
                    rejected = await drain(second)
                    code = second.close_code
                await first.send(json.dumps({"type": "end"}))
                await drain(first)
            return rejected, code

        rejected, code = run(scenario())
    assert rejected[-1]["code"] == "stt_capacity_reached" and code == 1013


# ---------------------------------------------------------------- privacy end to end

def test_nothing_sensitive_is_logged_even_at_debug_level(caplog):
    script = {1: [results("PRIVATE-spoken-words")], 2: [results("PRIVATE-spoken-words final", is_final=True)]}
    with FakeDeepgramServer(on_audio=script) as deepgram, LiveApp(deepgram, log_level="DEBUG") as live:
        configure_logging("DEBUG")  # what the app does for LOG_LEVEL=DEBUG
        caplog.set_level(logging.DEBUG)

        async def scenario():
            async with connect(live.url) as ws:
                await ws.send(json.dumps(CONFIG))
                ready = await recv_json(ws)
                await ws.send(b"\x09\x00" * 160)
                await ws.send(CHUNK)
                await recv_json(ws)
                await ws.send(json.dumps({"type": "end"}))
                await drain(ws)
                return ready

        ready = run(scenario())
        time.sleep(0.2)
    for forbidden in ("PRIVATE-spoken-words", KEY, ready["stream_id"], "Authorization", "Token "):
        assert forbidden not in caplog.text, forbidden
    assert "stt stream finished: outcome=completed" in caplog.text
