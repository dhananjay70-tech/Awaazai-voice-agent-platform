"""POST /tts/stream against a fake provider: progressive delivery, errors, cancellation, limits, headers, logging.

Driven through the raw ASGI interface (tests/asgi_client.py) because TestClient buffers the whole response and could
not show progressive delivery or disconnect handling. Every scenario runs under a hard wall-clock cap.
"""

import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from app.errors import (
    TtsAuthError,
    TtsProviderError,
    TtsRateLimitError,
    TtsTimeoutError,
    TtsUnavailableError,
)
from app.main import create_app
from app.tts.response import AudioStreamInterrupted
from tests.asgi_client import Call, wait_until
from tests.conftest import make_settings
from tests.tts_fakes import FakeTTSProvider

BODY = {"text": "Namaste! Main AwaazAI hoon.", "language": "hinglish"}
SECRET_TEXT = "TOP-SECRET-SENTENCE-12345"
SECRET_KEY = "dg-secret-key-do-not-leak"


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


def make_app(provider, **settings):
    return create_app(make_settings(**settings), tts_provider=provider)


def service_of(app):
    return app.state.tts_service


async def read_all(call: Call) -> bytes:
    audio = b""
    while (body := await call.next_body()) is not None:
        audio += body
    return audio


async def assert_clean(app, provider):
    await wait_until(lambda: service_of(app).limiter.in_use == 0 and provider.in_flight == 0)
    await asyncio.sleep(0.05)
    current = asyncio.current_task()
    stray = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    assert not stray, f"leaked tasks: {[t.get_name() for t in stray]}"


# ---------------------------------------------------------------- 1-2. progressive delivery, content type, headers

def test_audio_chunks_arrive_progressively_with_correct_headers():
    gates = [asyncio.Event() for _ in range(3)]
    provider = FakeTTSProvider([b"AAAA", b"BBBB", b"CCCC"], chunk_gates=gates)

    async def scenario():
        app = make_app(provider)
        call = Call(app, BODY, path="/tts/stream")
        gates[0].set()
        assert await call.read_start() == 200
        assert call.headers["content-type"] == "audio/mpeg"
        assert "no-store" in call.headers["cache-control"]
        assert call.headers["x-accel-buffering"] == "no"
        assert await call.next_body() == b"AAAA"
        assert call.no_message_pending()  # the later chunks have not been produced yet: nothing was buffered
        gates[1].set()
        assert await call.next_body() == b"BBBB"
        gates[2].set()
        assert await call.next_body() == b"CCCC"
        assert await call.next_body() is None
        await call.finished()
        assert provider.calls == [(BODY["text"], "aura-2-thalia-en")]
        await assert_clean(app, provider)

    run(scenario())


def test_request_id_and_security_headers_on_success_and_error():
    async def scenario():
        ok = Call(make_app(FakeTTSProvider()), BODY, path="/tts/stream")
        await ok.read_start()
        await read_all(ok)
        for headers in (ok.headers,):
            assert headers["x-content-type-options"] == "nosniff"
            assert headers["x-frame-options"] == "DENY"
            assert headers["referrer-policy"] == "no-referrer"
            assert "default-src 'none'" in headers["content-security-policy"]
            assert len(headers["x-request-id"]) == 16

        bad = Call(make_app(None), BODY, path="/tts/stream")
        await bad.read_start()
        body = await bad.json_body()
        assert bad.headers["x-request-id"] == body["error"]["request_id"]
        assert bad.headers["x-content-type-options"] == "nosniff"

    run(scenario())


# ---------------------------------------------------------------- 3-5. request validation, missing key

@pytest.mark.parametrize(
    "body",
    [
        {"text": ""},
        {"text": "   \n "},
        {},
        {"text": "hi", "language": "klingon"},
        {"text": "hi", "voice": "not a voice!"},
        {"text": "hi", "extra": 1},
        {"text": "x" * 2001},
        {"text": 123},
    ],
)
def test_invalid_requests_are_422_validation_errors_without_calling_the_provider(body):
    provider = FakeTTSProvider()
    with TestClient(make_app(provider), raise_server_exceptions=False) as client:
        response = client.post("/tts/stream", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert provider.started == 0


def test_unknown_voice_is_rejected_not_passed_through():
    provider = FakeTTSProvider()
    with TestClient(make_app(provider), raise_server_exceptions=False) as client:
        response = client.post("/tts/stream", json={"text": "hi", "voice": "aura-2-zeus-en"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "tts_invalid_voice"
    assert provider.started == 0


def test_configured_extra_voice_and_default_alias_are_accepted():
    provider = FakeTTSProvider()
    with TestClient(make_app(provider, deepgram_tts_voices="aura-2-zeus-en"), raise_server_exceptions=False) as client:
        assert client.post("/tts/stream", json={"text": "a", "voice": "aura-2-zeus-en"}).status_code == 200
        assert client.post("/tts/stream", json={"text": "b", "voice": "default"}).status_code == 200
    assert [voice for _, voice in provider.calls] == ["aura-2-zeus-en", "aura-2-thalia-en"]


def test_all_three_languages_are_accepted_and_text_is_sent_unchanged():
    provider = FakeTTSProvider()
    texts = {"english": "Hello there", "hindi": "नमस्ते, आप कैसे हैं?", "hinglish": "Aap kaise ho?"}
    with TestClient(make_app(provider), raise_server_exceptions=False) as client:
        for language, text in texts.items():
            response = client.post("/tts/stream", json={"text": f"  {text}  ", "language": language})
            assert response.status_code == 200 and response.headers["content-type"] == "audio/mpeg"
    assert [text for text, _ in provider.calls] == list(texts.values())  # trimmed, never translated or rewritten


def test_configured_max_text_length_is_enforced():
    provider = FakeTTSProvider()
    with TestClient(make_app(provider, tts_max_text_chars=10), raise_server_exceptions=False) as client:
        response = client.post("/tts/stream", json={"text": "x" * 11})
    assert response.status_code == 422 and response.json()["error"]["code"] == "tts_text_too_long"
    assert provider.started == 0


def test_missing_api_key_reports_tts_not_configured_and_service_starts():
    with TestClient(create_app(make_settings()), raise_server_exceptions=False) as client:
        assert client.get("/health").status_code == 200
        response = client.post("/tts/stream", json=BODY)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "tts_not_configured"


# ---------------------------------------------------------------- 6-10. provider failures before audio -> real HTTP status

@pytest.mark.parametrize(
    "error, status, code",
    [
        (TtsAuthError(), 502, "tts_authentication_failed"),
        (TtsRateLimitError(), 429, "tts_rate_limited"),
        (TtsTimeoutError(), 504, "tts_timeout"),
        (TtsUnavailableError(), 503, "tts_unavailable"),
        (TtsProviderError(), 502, "tts_provider_error"),
        (RuntimeError(f"boom {SECRET_TEXT} {SECRET_KEY}"), 500, "internal_error"),
    ],
)
def test_provider_failure_before_audio_is_a_json_error_with_a_real_status(error, status, code):
    provider = FakeTTSProvider(error=error)

    async def scenario():
        app = make_app(provider)
        call = Call(app, BODY, path="/tts/stream")
        assert await call.read_start() == status
        body = await call.json_body()
        assert body["error"]["code"] == code
        assert SECRET_TEXT not in str(body) and SECRET_KEY not in str(body)
        await call.finished()
        await assert_clean(app, provider)

    run(scenario())


def test_empty_audio_from_provider_is_a_502_not_a_fake_success():
    provider = FakeTTSProvider(chunks=[])

    async def scenario():
        app = make_app(provider)
        call = Call(app, BODY, path="/tts/stream")
        assert await call.read_start() == 502
        assert (await call.json_body())["error"]["code"] == "tts_bad_response"
        await assert_clean(app, provider)

    run(scenario())


def test_provider_that_yields_only_empty_chunks_is_a_502():
    provider = FakeTTSProvider(chunks=[b"", b""])

    async def scenario():
        app = make_app(provider)
        call = Call(app, BODY, path="/tts/stream")
        assert await call.read_start() == 502
        await assert_clean(app, provider)

    run(scenario())


def test_provider_silence_before_first_chunk_times_out_with_504_and_cleans_up():
    provider = FakeTTSProvider(chunk_gates=[asyncio.Event()])  # never opened: the provider never answers

    async def scenario():
        app = make_app(provider, tts_timeout_seconds=0.1)
        call = Call(app, BODY, path="/tts/stream")
        assert await call.read_start() == 504
        assert (await call.json_body())["error"]["code"] == "tts_timeout"
        assert provider.cancelled and provider.closed == 1
        await assert_clean(app, provider)

    run(scenario())


# ---------------------------------------------------------------- failures AFTER audio started: abort, never a clean end

def test_failure_mid_stream_aborts_the_connection_instead_of_ending_cleanly():
    provider = FakeTTSProvider([b"AAAA", b"BBBB"], error=TtsUnavailableError(), error_after=1)

    async def scenario():
        app = make_app(provider)
        call = Call(app, BODY, path="/tts/stream")
        assert await call.read_start() == 200
        assert await call.next_body() == b"AAAA"
        with pytest.raises(AudioStreamInterrupted, match="tts_unavailable"):
            await call.finished()
        # the terminating (more_body=False) message was never sent: the client sees a truncated download
        assert not call._complete
        await assert_clean(app, provider)

    run(scenario())


def test_provider_silence_mid_stream_times_out_and_aborts():
    provider = FakeTTSProvider([b"AAAA", b"BBBB"], hang_after=1)

    async def scenario():
        app = make_app(provider, tts_timeout_seconds=0.1)
        call = Call(app, BODY, path="/tts/stream")
        await call.read_start()
        assert await call.next_body() == b"AAAA"
        with pytest.raises(AudioStreamInterrupted, match="tts_timeout"):
            await call.finished()
        assert provider.cancelled
        await assert_clean(app, provider)

    run(scenario())


def test_total_stream_limit_stops_a_provider_that_trickles_forever():
    class Trickle(FakeTTSProvider):
        async def stream(self, *, text, voice, language=None):
            self.started += 1
            self.in_flight += 1
            try:
                while True:
                    await asyncio.sleep(0.03)
                    yield b"x"
            finally:
                self.in_flight -= 1
                self.closed += 1

    provider = Trickle()

    async def scenario():
        app = make_app(provider, tts_stream_timeout_seconds=0.2, tts_timeout_seconds=5)
        call = Call(app, BODY, path="/tts/stream")
        await call.read_start()
        with pytest.raises(AudioStreamInterrupted, match="tts_timeout"):
            await call.finished()
        await assert_clean(app, provider)

    run(scenario())


# ---------------------------------------------------------------- 11. client disconnect

def test_disconnect_mid_stream_cancels_upstream_and_releases_the_slot():
    provider = FakeTTSProvider([b"AAAA", b"BBBB"], hang_after=1)

    async def scenario():
        app = make_app(provider)
        call = Call(app, BODY, path="/tts/stream")
        await call.read_start()
        assert await call.next_body() == b"AAAA"
        assert service_of(app).limiter.in_use == 1

        call.disconnect()
        await call.finished()  # the app returns promptly
        assert provider.cancelled and provider.closed == 1
        await assert_clean(app, provider)

    run(scenario())


def test_disconnect_before_first_audio_cancels_upstream_and_replies_499():
    provider = FakeTTSProvider(chunk_gates=[asyncio.Event()])  # the provider is still thinking

    async def scenario():
        app = make_app(provider)
        call = Call(app, BODY, path="/tts/stream")
        await wait_until(lambda: provider.started == 1)
        call.disconnect()
        await call.finished()
        assert await call.read_start() == 499
        assert provider.cancelled and provider.closed == 1
        await assert_clean(app, provider)

    run(scenario())


def test_stalled_client_is_dropped_after_the_send_timeout():
    provider = FakeTTSProvider([b"x%d" % i for i in range(100)])

    async def scenario():
        app = make_app(provider, tts_send_timeout_seconds=0.15)
        call = Call(app, BODY, path="/tts/stream", stall_after_bodies=2)  # stops reading after 2 chunks
        await wait_until(lambda: provider.closed == 1)  # the server gives up on its own, within the send timeout
        # Only the transport-level send blocked on the stalled client remains (it belongs to the web server).
        await wait_until(lambda: service_of(app).limiter.in_use == 0 and provider.in_flight == 0)
        call.task.cancel()
        await asyncio.gather(call.task, return_exceptions=True)

    run(scenario())


def test_slow_provider_cleanup_is_awaited_before_the_slot_is_released():
    provider = FakeTTSProvider([b"AAAA", b"BBBB"], hang_after=1, cleanup_delay=0.1)

    async def scenario():
        app = make_app(provider)
        call = Call(app, BODY, path="/tts/stream")
        await call.read_start()
        await call.next_body()
        call.disconnect()
        await call.finished()
        assert provider.closed == 1 and provider.in_flight == 0  # cleanup completed before the app returned
        assert service_of(app).limiter.in_use == 0

    run(scenario())


# ---------------------------------------------------------------- 12. concurrency limit and slot release

def test_concurrency_limit_rejects_excess_requests_with_503_and_slots_are_released():
    gates = [asyncio.Event()]
    provider = FakeTTSProvider([b"AAAA", b"BBBB"], chunk_gates=gates)

    async def scenario():
        app = make_app(provider, tts_max_concurrent_requests=2, tts_queue_timeout_seconds=0)
        first = Call(app, BODY, path="/tts/stream")
        second = Call(app, BODY, path="/tts/stream")
        await wait_until(lambda: provider.in_flight == 2)

        third = Call(app, BODY, path="/tts/stream")
        assert await third.read_start() == 503
        assert (await third.json_body())["error"]["code"] == "tts_capacity_reached"
        assert provider.max_in_flight == 2 and provider.started == 2

        gates[0].set()
        for call in (first, second):
            assert await call.read_start() == 200
            assert await read_all(call) == b"AAAABBBB"
            await call.finished()
        await wait_until(lambda: service_of(app).limiter.in_use == 0)

        fourth = Call(app, BODY, path="/tts/stream")  # a slot is free again
        assert await fourth.read_start() == 200
        await read_all(fourth)
        await assert_clean(app, provider)

    run(scenario())


def test_slot_is_released_after_provider_errors():
    provider = FakeTTSProvider(error=TtsProviderError())

    async def scenario():
        app = make_app(provider, tts_max_concurrent_requests=1, tts_queue_timeout_seconds=0)
        for _ in range(3):
            call = Call(app, BODY, path="/tts/stream")
            assert await call.read_start() == 502  # a leaked slot would turn the 2nd request into a 503
            await call.json_body()
            await call.finished()
        await assert_clean(app, provider)

    run(scenario())


def test_tts_limit_is_independent_of_the_gemini_and_stt_limits():
    app = make_app(FakeTTSProvider(), tts_max_concurrent_requests=1, llm_max_concurrent_generations=7, stt_max_concurrent_streams=3)
    assert app.state.tts_service.limiter is not app.state.chat_service.limiter
    assert app.state.tts_service.limiter is not app.state.stt_service.limiter
    assert app.state.tts_service.limiter.max_concurrent == 1
    assert app.state.chat_service.limiter.max_concurrent == 7
    assert app.state.stt_service.limiter.max_concurrent == 3


# ---------------------------------------------------------------- 14. no leakage in logs

def test_logs_never_contain_text_audio_or_credentials(caplog):
    caplog.set_level(logging.DEBUG)
    ok = FakeTTSProvider([b"AUDIO-BYTES-SECRET"])
    failing = FakeTTSProvider([b"AUDIO-BYTES-SECRET"], error=RuntimeError(f"{SECRET_TEXT} {SECRET_KEY}"), error_after=0)

    async def scenario():
        for provider, secret_in_body in ((ok, True), (failing, True)):
            app = make_app(provider, deepgram_api_key=SECRET_KEY)
            call = Call(app, {"text": SECRET_TEXT, "language": "english"}, path="/tts/stream")
            await call.read_start()
            await call.json_body() if call.status != 200 else await read_all(call)

    run(scenario())
    logged = caplog.text
    assert "tts stream finished" in logged
    for secret in (SECRET_TEXT, SECRET_KEY, "AUDIO-BYTES-SECRET"):
        assert secret not in logged
