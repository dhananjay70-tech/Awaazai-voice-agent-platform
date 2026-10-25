"""WS /stt/stream protocol: events and ordering, languages, validation, errors, origin, headers, privacy."""

import asyncio
import logging

import pytest

from app.errors import (
    SttAuthError,
    SttBadResponseError,
    SttInvalidAudioError,
    SttProviderError,
    SttRateLimitError,
    SttTimeoutError,
    SttUnavailableError,
)
from app.main import create_app
from tests.asgi_client import WsCall
from tests.conftest import make_settings
from tests.stt_fakes import FakeSTTProvider, FakeSTTSession, final, partial

CHUNK = b"\x01\x00" * 160  # 10 ms of 16 kHz mono 16-bit PCM = 320 bytes
CONFIG = {"type": "config", "encoding": "linear16", "sample_rate": 16000, "channels": 1, "language": "hinglish"}


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


def make_app(provider, **settings):
    return create_app(make_settings(**settings), stt_provider=provider)


async def start(app, config=CONFIG, headers=None):
    """Connect, send the config, and return (call, ready_event)."""
    call = WsCall(app, headers=headers)
    assert await call.wait_accepted()
    call.send_json(config)
    return call, await call.next_event()


def names(events):
    return [e["type"] for e in events]


# ---------------------------------------------------------------- partial / final events and ordering

def test_full_stream_emits_ready_partials_finals_done_in_order():
    provider = FakeSTTProvider(
        on_chunk={1: [partial("namaste")], 2: [partial("namaste duniya")], 3: [final("namaste duniya", speech_final=True)]},
        on_finish=[final("kaise ho", start=1.0)],
    )

    async def scenario():
        call, ready = await start(make_app(provider))
        for _ in range(3):
            call.send_bytes(CHUNK)
        call.send_json({"type": "end"})
        events = [ready] + await call.events()
        await call.finished()
        return call, events

    call, events = run(scenario())
    assert names(events) == ["ready", "partial", "partial", "final", "final", "done"]
    assert call.close_code == 1000

    ready, p1, p2, f1, f2, done = events
    assert ready["language"] == "hinglish" and ready["model"] == "fake-stt-model"
    assert (ready["sample_rate"], ready["channels"]) == (16000, 1) and len(ready["stream_id"]) == 32
    assert [e["text"] for e in (p1, p2, f1, f2)] == ["namaste", "namaste duniya", "namaste duniya", "kaise ho"]
    assert [e["seq"] for e in (p1, p2, f1, f2)] == [1, 2, 3, 4]  # strictly increasing across partials and finals
    assert f1["speech_final"] is True and f2["speech_final"] is False and f2["start"] == 1.0
    assert set(f1) == {"type", "seq", "text", "start", "duration", "speech_final", "confidence"}
    assert set(p1) == {"type", "seq", "text"}
    assert done["partials"] == 2 and done["finals"] == 2 and done["audio_seconds"] == 0.03
    assert done["stream_id"] == ready["stream_id"]

    session = provider.last
    assert session.audio_bytes == 3 * len(CHUNK) and session.finished and session.closed
    language, audio = provider.opened[0]
    assert language == "hinglish" and (audio.encoding, audio.sample_rate, audio.channels) == ("linear16", 16000, 1)


def test_repeated_partials_are_not_sent_again_but_reappear_after_a_final():
    provider = FakeSTTProvider(on_chunk={
        1: [partial("hello"), partial("hello"), partial("hello")],
        2: [partial("hello"), final("hello", speech_final=True)],
        # a NEW segment starts and its first hypothesis is word-for-word the one heard just before the final:
        # that is news again, so it must be sent (and then de-duplicated as usual)
        3: [partial("hello"), partial("hello")],
    })

    async def scenario():
        call, _ = await start(make_app(provider))
        for _ in range(3):
            call.send_bytes(CHUNK)
        call.send_json({"type": "end"})
        return await call.events()

    events = run(scenario())
    assert [(e["type"], e.get("text")) for e in events[:-1]] == [
        ("partial", "hello"), ("final", "hello"), ("partial", "hello"),
    ]


def test_events_are_forwarded_as_they_arrive_not_after_the_stream_ends():
    provider = FakeSTTProvider(on_chunk={1: [partial("first words")], 2: [final("first words")]})

    async def scenario():
        call, _ = await start(make_app(provider))
        call.send_bytes(CHUNK)
        assert (await call.next_event())["text"] == "first words"  # arrives while the client is still speaking
        assert call.nothing_pending()
        call.send_bytes(CHUNK)
        assert (await call.next_event())["type"] == "final"
        call.send_json({"type": "end"})
        assert (await call.next_event())["type"] == "done"

    run(scenario())


def test_stream_without_any_speech_completes_cleanly():
    provider = FakeSTTProvider()

    async def scenario():
        call, _ = await start(make_app(provider))
        for _ in range(3):
            call.send_bytes(CHUNK)  # silence: the provider returns nothing
        call.send_json({"type": "end"})
        return await call.events()

    events = run(scenario())
    assert names(events) == ["done"] and events[0]["partials"] == 0 and events[0]["finals"] == 0
    assert events[0]["first_partial_ms"] is None and events[0]["first_final_ms"] is None


# ---------------------------------------------------------------- languages and audio formats

@pytest.mark.parametrize("language", ["english", "hindi", "hinglish"])
def test_language_is_passed_to_the_provider(language):
    provider = FakeSTTProvider()

    async def scenario():
        call, ready = await start(make_app(provider), {**CONFIG, "language": language})
        call.send_json({"type": "end"})
        await call.events()
        return ready

    assert run(scenario())["language"] == language
    assert provider.opened[0][0] == language


def test_language_defaults_to_hinglish_when_omitted():
    provider = FakeSTTProvider()
    config = {"type": "config", "sample_rate": 16000}

    async def scenario():
        call, ready = await start(make_app(provider), config)
        call.send_json({"type": "end"})
        await call.events()
        return ready

    assert run(scenario())["language"] == "hinglish"
    assert provider.opened[0][1].channels == 1 and provider.opened[0][1].encoding == "linear16"


@pytest.mark.parametrize("rate", [8000, 16000, 22050, 24000, 44100, 48000])
def test_all_supported_sample_rates_are_accepted(rate):
    provider = FakeSTTProvider()

    async def scenario():
        call, ready = await start(make_app(provider), {**CONFIG, "sample_rate": rate})
        call.send_bytes(b"\x00\x00" * 100)
        call.send_json({"type": "end"})
        return ready, await call.events()

    ready, events = run(scenario())
    assert ready["sample_rate"] == rate and events[-1]["type"] == "done"


# ---------------------------------------------------------------- invalid config: nothing reaches the provider

BAD_CONFIGS = {
    "not json": "this is {not json",
    "json but not an object": "[1, 2]",
    "missing sample_rate": {"type": "config"},
    "sample_rate not an int": {**CONFIG, "sample_rate": "16000"},
    "unsupported sample_rate": {**CONFIG, "sample_rate": 12345},
    "unsupported encoding": {**CONFIG, "encoding": "mulaw"},
    "opus encoding": {**CONFIG, "encoding": "opus"},
    "stereo": {**CONFIG, "channels": 2},
    "zero channels": {**CONFIG, "channels": 0},
    "unknown language": {**CONFIG, "language": "klingon"},
    "wrong case language": {**CONFIG, "language": "Hindi"},
    "wrong type": {**CONFIG, "type": "start"},
    "extra field": {**CONFIG, "user_id": "someone-else"},
    "extra provider option": {**CONFIG, "model": "other-model"},
}


@pytest.mark.parametrize("name", list(BAD_CONFIGS))
def test_invalid_config_is_rejected_before_the_provider_is_used(name):
    provider = FakeSTTProvider()

    async def scenario():
        call = WsCall(make_app(provider))
        assert await call.wait_accepted()
        payload = BAD_CONFIGS[name]
        call.send_json(payload) if not isinstance(payload, str) else call.send_text(payload)
        events = await call.events()
        await call.finished()
        return call, events

    call, events = run(scenario())
    assert names(events) == ["error"] and events[0]["code"] == "stt_invalid_config"
    assert call.close_code == 1008
    assert provider.opened == [] and provider.sessions == []


def test_audio_before_the_config_message_is_rejected():
    provider = FakeSTTProvider()

    async def scenario():
        call = WsCall(make_app(provider))
        await call.wait_accepted()
        call.send_bytes(CHUNK)
        return await call.events()

    events = run(scenario())
    assert events[0]["code"] == "stt_invalid_config" and provider.opened == []


def test_invalid_config_error_names_fields_but_never_echoes_values():
    provider = FakeSTTProvider()

    async def scenario():
        call = WsCall(make_app(provider))
        await call.wait_accepted()
        call.send_json({**CONFIG, "language": "SENSITIVE-value-123", "sample_rate": "SENSITIVE-rate", "secret_field": "SENSITIVE-x"})
        return await call.events()

    (event,) = run(scenario())
    fields = {d["field"] for d in event["details"]}
    assert {"language", "sample_rate", "secret_field"} <= fields
    assert "SENSITIVE" not in str(event)


def test_oversized_config_message_is_rejected():
    async def scenario():
        call = WsCall(make_app(FakeSTTProvider()))
        await call.wait_accepted()
        call.send_text('{"type":"config","sample_rate":16000,"pad":"' + "x" * 10_000 + '"}')
        return await call.events()

    assert run(scenario())[0]["code"] == "stt_invalid_config"


# ---------------------------------------------------------------- invalid audio and stream limits

def invalid_stream(frames, **settings):
    provider = FakeSTTProvider()

    async def scenario():
        call, _ = await start(make_app(provider, **settings))
        for frame in frames:
            call.send_bytes(frame)
        events = await call.events()
        await call.finished()
        return call, events

    call, events = run(scenario())
    return call, events, provider


def test_odd_length_frame_is_not_whole_pcm16_samples():
    call, events, provider = invalid_stream([CHUNK, b"\x00\x00\x00"])
    assert events[-1]["code"] == "stt_invalid_audio" and call.close_code == 1008
    assert provider.last.closed and provider.last.audio_bytes == len(CHUNK)  # the bad frame was never forwarded


def test_empty_frame_is_rejected():
    call, events, _ = invalid_stream([b""])
    assert events[-1]["code"] == "stt_invalid_audio"


def test_oversized_chunk_is_rejected_with_the_too_big_close_code():
    call, events, provider = invalid_stream([b"\x00\x00" * 200], stt_max_chunk_bytes=320)
    assert events[-1]["code"] == "stt_limit_exceeded" and call.close_code == 1009
    assert provider.last.audio_bytes == 0


def test_chunk_exactly_at_the_limit_is_accepted():
    provider = FakeSTTProvider()

    async def scenario():
        call, _ = await start(make_app(provider, stt_max_chunk_bytes=320))
        call.send_bytes(b"\x00\x00" * 160)
        call.send_json({"type": "end"})
        return await call.events()

    assert names(run(scenario())) == ["done"]


def test_total_audio_duration_limit_ends_the_stream():
    # 6 frames of 10 ms = 60 ms > a 50 ms budget
    call, events, provider = invalid_stream([CHUNK] * 6, stt_max_audio_seconds=0.05)
    assert events[-1]["code"] == "stt_limit_exceeded" and call.close_code == 1009
    assert provider.last.closed and provider.last.audio_bytes < 6 * len(CHUNK)


def test_audio_sent_much_faster_than_real_time_is_rejected():
    # 20 s of audio in a burst, far beyond the 10 s burst allowance + 2x real time
    frame = b"\x00\x00" * 16000  # 1 s of 16 kHz audio = 32000 bytes
    call, events, _ = invalid_stream([frame] * 20, stt_max_chunk_bytes=32000, stt_max_audio_seconds=600)
    assert events[-1]["code"] == "stt_limit_exceeded"
    assert "faster than real time" in events[-1]["message"]


@pytest.mark.parametrize("message", ['{"type":"start"}', '{"type":"end","extra":1}', "not json", '{"type":"config","sample_rate":16000}', "[]"])
def test_unsupported_control_messages_are_rejected(message):
    provider = FakeSTTProvider()

    async def scenario():
        call, _ = await start(make_app(provider))
        call.send_text(message)
        return await call.events()

    events = run(scenario())
    assert events[-1]["code"] == "stt_invalid_config" and provider.last.closed


# ---------------------------------------------------------------- not configured / provider failures

def test_missing_api_key_gives_a_clear_error_and_health_still_works():
    app = make_app(None)

    async def scenario():
        call = WsCall(app)
        assert await call.wait_accepted()
        return call, await call.events()

    call, events = run(scenario())
    assert names(events) == ["error"] and events[0]["code"] == "stt_not_configured" and "DEEPGRAM_API_KEY" in events[0]["message"]
    assert call.close_code == 1011
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


OPEN_ERRORS = [
    (SttAuthError(), "stt_authentication_failed", 1011),
    (SttRateLimitError(), "stt_rate_limited", 1011),
    (SttUnavailableError(), "stt_unavailable", 1011),
    (SttTimeoutError(), "stt_timeout", 1011),
    (SttProviderError(), "stt_provider_error", 1011),
]


@pytest.mark.parametrize("error,code,close", OPEN_ERRORS)
def test_provider_errors_when_connecting_become_safe_error_events(error, code, close):
    provider = FakeSTTProvider(open_error=error)

    async def scenario():
        call = WsCall(make_app(provider))
        await call.wait_accepted()
        call.send_json(CONFIG)
        events = await call.events()
        await call.finished()
        return call, events

    call, events = run(scenario())
    assert names(events) == ["error"] and events[0]["code"] == code and call.close_code == close
    assert set(events[0]) == {"type", "code", "message", "request_id"}


MIDSTREAM_ERRORS = OPEN_ERRORS + [
    (SttBadResponseError(), "stt_bad_response", 1011),
    (SttInvalidAudioError("The speech-to-text provider could not decode the audio."), "stt_invalid_audio", 1008),
]


@pytest.mark.parametrize("error,code,close", MIDSTREAM_ERRORS)
def test_provider_errors_mid_stream_become_safe_error_events_after_earlier_results(error, code, close):
    provider = FakeSTTProvider(on_chunk={1: [partial("already heard")]}, error_at_chunk=2, error=error)

    async def scenario():
        call, _ = await start(make_app(provider))
        call.send_bytes(CHUNK)
        call.send_bytes(CHUNK)
        events = await call.events()
        await call.finished()
        return call, events

    call, events = run(scenario())
    assert names(events) == ["partial", "error"] and events[-1]["code"] == code and call.close_code == close
    assert provider.last.closed and provider.last.events_cancelled is False  # it ended by itself: nothing left running


def test_provider_ending_the_stream_by_itself_is_reported_as_an_error():
    provider = FakeSTTProvider(on_chunk={1: [partial("hi")]}, end_after_chunk=1)

    async def scenario():
        call, _ = await start(make_app(provider))
        call.send_bytes(CHUNK)
        return await call.events()

    events = run(scenario())
    assert events[-1]["code"] == "stt_provider_error" and "unexpectedly" in events[-1]["message"]


def test_unexpected_exception_is_generic_and_hides_details():
    provider = FakeSTTProvider(error_at_chunk=1, error=RuntimeError("SENSITIVE-internal-detail-42"))

    async def scenario():
        call, _ = await start(make_app(provider))
        call.send_bytes(CHUNK)
        return await call.events()

    events = run(scenario())
    assert events[-1]["code"] == "internal_error" and "SENSITIVE" not in str(events)


# ---------------------------------------------------------------- origin check (browser security)

def accepted_with_origin(origin):
    async def scenario():
        headers = {"origin": origin} if origin is not None else None
        call = WsCall(make_app(FakeSTTProvider()), headers=headers)
        accepted = await call.wait_accepted()
        if accepted:
            call.send_json(CONFIG)
            await call.next_event()
            call.send_json({"type": "end"})
            await call.events()
        return accepted, call

    return run(scenario())


def test_listed_origin_is_accepted():
    assert accepted_with_origin("http://localhost:5173")[0] is True


def test_missing_origin_header_is_accepted_for_non_browser_clients():
    assert accepted_with_origin(None)[0] is True


@pytest.mark.parametrize("origin", ["http://evil.example", "https://localhost:5173", "http://localhost:5174", "null", ""])
def test_unlisted_origin_is_refused_before_the_handshake_completes(origin):
    accepted, call = accepted_with_origin(origin)
    assert accepted is False and call.rejected and call.close_code == 1008


def test_wildcard_origin_setting_allows_any_origin_outside_production():
    async def scenario():
        call = WsCall(make_app(FakeSTTProvider(), stt_allowed_origins="*"), headers={"origin": "http://anything.example"})
        return await call.wait_accepted()

    assert run(scenario()) is True


# ---------------------------------------------------------------- request ids and security headers

def test_handshake_response_carries_request_id_and_security_headers():
    async def scenario():
        call, ready = await start(make_app(FakeSTTProvider()))
        call.send_json({"type": "end"})
        await call.events()
        return call, ready

    call, ready = run(scenario())
    assert len(call.accept_headers["x-request-id"]) == 16
    assert call.accept_headers["x-content-type-options"] == "nosniff"
    assert call.accept_headers["cache-control"] == "no-store"
    assert ready["request_id"] == call.accept_headers["x-request-id"]


def test_error_events_carry_the_same_request_id_and_each_stream_has_its_own():
    async def one():
        call = WsCall(make_app(FakeSTTProvider(open_error=SttProviderError())))
        await call.wait_accepted()
        call.send_json(CONFIG)
        (event,) = await call.events()
        return call.accept_headers["x-request-id"], event["request_id"]

    first, second = run(one()), run(one())
    assert first[0] == first[1] and second[0] == second[1] and first[0] != second[0]


# ---------------------------------------------------------------- privacy

def test_logs_never_contain_audio_transcripts_keys_or_ids(caplog):
    provider = FakeSTTProvider(on_chunk={1: [partial("PRIVATE-transcript-words")], 2: [final("PRIVATE-final-words")]})

    async def scenario():
        app = make_app(provider)
        caplog.set_level(logging.DEBUG)
        call, ready = await start(app)
        call.send_bytes(b"\x07\x00" * 160)
        call.send_bytes(CHUNK)
        call.send_json({"type": "end"})
        events = await call.events()
        await call.finished()
        return ready, events

    ready, events = run(scenario())
    for forbidden in ("PRIVATE", ready["stream_id"], ready["request_id"] + "SECRET"):
        assert forbidden not in caplog.text, forbidden
    assert "stt stream finished: outcome=completed" in caplog.text and "language=hinglish" in caplog.text


def test_unexpected_error_logs_type_and_frames_but_not_the_message(caplog):
    provider = FakeSTTProvider(error_at_chunk=1, error=RuntimeError("PRIVATE-transcript-in-error-message"))

    async def scenario():
        app = make_app(provider)
        caplog.set_level(logging.DEBUG)
        call, _ = await start(app)
        call.send_bytes(CHUNK)
        await call.events()

    run(scenario())
    assert "PRIVATE-transcript-in-error-message" not in caplog.text
    assert "RuntimeError" in caplog.text and "stt stream finished: outcome=failed" in caplog.text


# ---------------------------------------------------------------- regression: other endpoints are untouched

def test_health_chat_and_chat_stream_still_work_alongside_stt():
    from fastapi.testclient import TestClient

    from tests.conftest import FakeProvider

    app = create_app(make_settings(), llm_provider=FakeProvider(), stt_provider=FakeSTTProvider())
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.post("/chat", json={"message": "hi", "session_id": "s"}).json()["reply"] == "fake-reply-1"
        assert client.post("/chat/stream", json={"message": "hi"}).status_code == 200
        assert "/stt/stream" not in client.get("/openapi.json").json()["paths"]  # a WebSocket is not an HTTP operation
