"""STT stream lifecycle: timeouts, disconnects, stalled clients, cleanup ordering, resource release, concurrency."""

import asyncio
import logging

import pytest

from app.errors import SttProviderError
from app.main import create_app
from tests.asgi_client import WsCall, wait_until
from tests.conftest import make_settings
from tests.stt_fakes import FakeSTTProvider, FakeSTTSession, final, partial

CHUNK = b"\x01\x00" * 160  # 10 ms of 16 kHz mono PCM16
CONFIG = {"type": "config", "encoding": "linear16", "sample_rate": 16000, "channels": 1, "language": "hinglish"}


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 25))


def make_app(provider, **settings):
    return create_app(make_settings(**settings), stt_provider=provider)


def service_of(app):
    return app.state.stt_service


async def start(app, headers=None, **call_kwargs):
    call = WsCall(app, headers=headers, **call_kwargs)
    assert await call.wait_accepted()
    call.send_json(CONFIG)
    return call, await call.next_event()


async def assert_clean(app, provider=None, allowed_tasks: int = 0):
    """Nothing may be left behind: no stream slot, no provider connection, no stray task."""
    await wait_until(lambda: service_of(app).limiter.in_use == 0)
    if provider is not None:
        assert all(s.closed for s in provider.sessions), "a provider session was left open"
    await asyncio.sleep(0.05)
    current = asyncio.current_task()
    stray = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    assert len(stray) <= allowed_tasks, f"leaked tasks: {[t.get_name() for t in stray]}"


# ---------------------------------------------------------------- idle and total timeouts

def test_idle_timeout_before_any_config_message():
    async def scenario():
        app = make_app(FakeSTTProvider(), stt_idle_timeout_seconds=0.15)
        call = WsCall(app)
        await call.wait_accepted()
        events = await call.events()  # the client never says anything
        await call.finished()
        assert events[-1]["code"] == "stt_idle_timeout" and call.close_code == 1008
        await assert_clean(app)

    run(scenario())


def test_idle_timeout_mid_stream_releases_everything():
    provider = FakeSTTProvider(on_chunk={1: [partial("spoken so far")]})

    async def scenario():
        app = make_app(provider, stt_idle_timeout_seconds=0.2)
        call, _ = await start(app)
        call.send_bytes(CHUNK)
        events = await call.events()  # then the client falls silent
        await call.finished()
        assert [e["type"] for e in events] == ["partial", "error"] and events[-1]["code"] == "stt_idle_timeout"
        assert provider.last.closed and provider.last.events_cancelled  # the provider side was cancelled and closed
        await assert_clean(app, provider)

    run(scenario())


def test_a_client_that_keeps_sending_never_hits_the_idle_timeout():
    provider = FakeSTTProvider()

    async def scenario():
        app = make_app(provider, stt_idle_timeout_seconds=0.3)
        call, _ = await start(app)
        for _ in range(8):  # continuous audio (including silence) for longer than the idle limit
            call.send_bytes(CHUNK)
            await asyncio.sleep(0.07)
        call.send_json({"type": "end"})
        events = await call.events()
        assert events[-1]["type"] == "done"

    run(scenario())


def test_total_stream_duration_limit():
    provider = FakeSTTProvider()

    async def scenario():
        app = make_app(provider, stt_max_stream_seconds=0.4, stt_idle_timeout_seconds=5)
        call, _ = await start(app)

        async def keep_talking():
            while True:
                call.send_bytes(CHUNK)
                await asyncio.sleep(0.05)

        talker = asyncio.create_task(keep_talking())
        events = await call.events()
        talker.cancel()
        await call.finished()
        assert events[-1]["code"] == "stt_stream_timeout" and call.close_code == 1008
        await assert_clean(app, provider)

    run(scenario())


def test_provider_that_never_finishes_after_end_times_out():
    provider = FakeSTTProvider(on_chunk={1: [partial("hello")]}, hang_on_finish=True)

    async def scenario():
        app = make_app(provider, stt_finish_timeout_seconds=0.2)
        call, _ = await start(app)
        call.send_bytes(CHUNK)
        call.send_json({"type": "end"})
        events = await call.events()
        await call.finished()
        assert events[-1]["code"] == "stt_timeout" and provider.last.finished
        await assert_clean(app, provider)

    run(scenario())


# ---------------------------------------------------------------- client disconnect / cancellation

def test_client_disconnect_mid_stream_cancels_the_provider_and_cleans_up(caplog):
    provider = FakeSTTProvider(on_chunk={1: [partial("hello")]})

    async def scenario():
        app = make_app(provider)
        caplog.set_level(logging.DEBUG)
        call, _ = await start(app)
        call.send_bytes(CHUNK)
        assert (await call.next_event())["type"] == "partial"
        assert service_of(app).limiter.in_use == 1

        call.disconnect()  # the browser tab was closed
        await call.finished()
        assert provider.last.closed and provider.last.events_cancelled and not provider.last.finished
        await assert_clean(app, provider)

    run(scenario())
    assert "stt stream finished: outcome=cancelled" in caplog.text


def test_client_disconnect_before_the_config_message():
    async def scenario():
        provider = FakeSTTProvider()
        app = make_app(provider)
        call = WsCall(app)
        await call.wait_accepted()
        call.disconnect()
        await call.finished()
        assert provider.sessions == []
        await assert_clean(app, provider)

    run(scenario())


def test_cancelling_the_handler_task_cleans_up_like_a_server_shutdown():
    provider = FakeSTTProvider(on_chunk={1: [partial("hello")]})

    async def scenario():
        app = make_app(provider)
        call, _ = await start(app)
        call.send_bytes(CHUNK)
        await call.next_event()
        call.task.cancel()
        await asyncio.gather(call.task, return_exceptions=True)
        assert provider.last.closed
        await assert_clean(app, provider)

    run(scenario())


def test_repeated_connect_and_disconnect_leaks_nothing():
    provider = FakeSTTProvider(on_chunk={1: [partial("x")]})

    async def scenario():
        app = make_app(provider, stt_max_concurrent_streams=2)
        for _ in range(25):
            call, _ = await start(app)
            call.send_bytes(CHUNK)
            await call.next_event()
            call.disconnect()
            await call.finished()
        assert len(provider.sessions) == 25 and all(s.closed for s in provider.sessions)
        await assert_clean(app, provider)
        call, _ = await start(app)  # still fully usable
        call.send_json({"type": "end"})
        assert (await call.events())[-1]["type"] == "done"

    run(scenario())


# ---------------------------------------------------------------- slow or stalled clients and backpressure

def test_client_that_stops_reading_events_cannot_hold_a_stream_forever():
    many = {n: [partial(f"text {n}"), final(f"final {n}")] for n in range(1, 40)}
    provider = FakeSTTProvider(on_chunk=many)

    async def scenario():
        app = make_app(provider, stt_send_timeout_seconds=0.15)
        call, _ = await start(app, stall_after_sends=2)  # reads the ready event, then stops reading
        for _ in range(10):
            call.send_bytes(CHUNK)
        await wait_until(lambda: provider.last.closed)  # the server dropped it on its own
        assert provider.last.events_cancelled
        await assert_clean(app, provider, allowed_tasks=1)  # one task: the transport send blocked on that client
        call.task.cancel()
        await asyncio.gather(call.task, return_exceptions=True)

    run(scenario())


def test_audio_is_not_read_ahead_of_the_provider():
    """The service reads the next client frame only after the provider accepted the previous one: no hidden buffer."""
    gate = asyncio.Event()
    provider = FakeSTTProvider(session_factory=lambda: FakeSTTSession(send_gate=gate))

    async def scenario():
        app = make_app(provider)
        call, _ = await start(app)
        for _ in range(6):
            call.send_bytes(CHUNK)
        await asyncio.sleep(0.15)
        assert provider.last.audio == []  # the provider is still blocked on frame 1...
        assert call._incoming.qsize() == 5, "frames 2-6 must still be unread (queued by the client, not by the server)"
        gate.set()
        await wait_until(lambda: len(provider.last.audio) == 6)
        call.send_json({"type": "end"})
        assert (await call.events())[-1]["type"] == "done"

    run(scenario())


def test_provider_session_is_closed_before_the_stream_slot_is_released():
    provider = FakeSTTProvider(session_factory=lambda: FakeSTTSession(close_delay=0.1))

    async def scenario():
        app = make_app(provider)
        call, _ = await start(app)
        call.send_json({"type": "end"})
        await call.events()
        await call.finished()
        assert provider.last.closed, "the handler returned before the provider connection was closed"
        assert service_of(app).limiter.in_use == 0

    run(scenario())


# ---------------------------------------------------------------- errors cancel the other direction

def test_invalid_audio_cancels_the_provider_event_reader():
    provider = FakeSTTProvider()

    async def scenario():
        app = make_app(provider)
        call, _ = await start(app)
        call.send_bytes(b"\x00")  # one byte: not a whole sample
        events = await call.events()
        await call.finished()
        assert events[-1]["code"] == "stt_invalid_audio"
        assert provider.last.events_cancelled and provider.last.closed
        await assert_clean(app, provider)

    run(scenario())


def test_provider_failure_stops_the_client_reader():
    provider = FakeSTTProvider(error_at_chunk=2, error=SttProviderError())

    async def scenario():
        app = make_app(provider)
        call, _ = await start(app)
        call.send_bytes(CHUNK)
        call.send_bytes(CHUNK)
        events = await call.events()
        await call.finished()
        assert events[-1]["code"] == "stt_provider_error"
        call.send_bytes(CHUNK)  # a late frame goes nowhere: nobody is reading any more
        await asyncio.sleep(0.05)
        assert len(provider.last.audio) == 2
        await assert_clean(app, provider)

    run(scenario())


# ---------------------------------------------------------------- concurrency limit

def test_concurrent_streams_are_limited_and_excess_gets_capacity_error():
    provider = FakeSTTProvider()

    async def scenario():
        app = make_app(provider, stt_max_concurrent_streams=2)
        first, _ = await start(app)
        second, _ = await start(app)
        third = WsCall(app)
        await third.wait_accepted()
        events = await third.events()
        await third.finished()
        assert events[-1]["code"] == "stt_capacity_reached" and third.close_code == 1013
        assert len(provider.sessions) == 2  # the rejected stream never reached the provider

        first.send_json({"type": "end"})
        await first.events()
        await first.finished()
        fourth, ready = await start(app)  # capacity is back
        assert ready["type"] == "ready"
        for call in (second, fourth):
            call.send_json({"type": "end"})
            await call.events()
        await assert_clean(app, provider)

    run(scenario())


def test_slot_is_released_after_every_kind_of_failure():
    from app.errors import SttAuthError

    async def scenario():
        app = make_app(FakeSTTProvider(open_error=SttAuthError()), stt_max_concurrent_streams=1)
        for _ in range(8):  # a single slot: any leak would turn the next attempt into stt_capacity_reached
            call = WsCall(app)
            await call.wait_accepted()
            call.send_json(CONFIG)
            events = await call.events()
            await call.finished()
            assert events[-1]["code"] == "stt_authentication_failed"
        for bad in (b"\x00", b"", b"\x00\x00" * 10_000):
            provider = FakeSTTProvider()
            app2 = make_app(provider, stt_max_concurrent_streams=1, stt_max_chunk_bytes=320)
            for _ in range(3):
                call, _ = await start(app2)
                call.send_bytes(bad)
                events = await call.events()
                await call.finished()
                assert events[-1]["code"] in ("stt_invalid_audio", "stt_limit_exceeded")
            await assert_clean(app2, provider)

    run(scenario())


def test_streams_are_isolated_from_each_other():
    sessions = iter([
        FakeSTTSession(on_chunk={1: [partial("from stream ONE")]}),
        FakeSTTSession(on_chunk={1: [partial("from stream TWO")]}),
    ])
    provider = FakeSTTProvider(session_factory=lambda: next(sessions))

    async def scenario():
        app = make_app(provider)
        one, ready_one = await start(app)
        two, ready_two = await start(app)
        one.send_bytes(CHUNK)
        two.send_bytes(CHUNK)
        assert (await one.next_event())["text"] == "from stream ONE"
        assert (await two.next_event())["text"] == "from stream TWO"
        assert ready_one["stream_id"] != ready_two["stream_id"]
        one.disconnect()  # one stream ending must not affect the other
        await one.finished()
        two.send_json({"type": "end"})
        assert (await two.events())[-1]["type"] == "done"
        await assert_clean(app, provider)

    run(scenario())


def test_stt_streams_do_not_touch_chat_sessions_or_the_text_generation_limit():
    from tests.conftest import FakeProvider

    llm = FakeProvider()
    stt = FakeSTTProvider()

    async def scenario():
        app = create_app(make_settings(llm_max_concurrent_generations=1), llm_provider=llm, stt_provider=stt)
        call, _ = await start(app)
        assert app.state.chat_service.limiter.in_use == 0  # separate limiters: STT does not use up Gemini slots
        assert len(app.state.chat_service._store) == 0  # and creates no chat session
        call.send_json({"type": "end"})
        await call.events()

    run(scenario())
