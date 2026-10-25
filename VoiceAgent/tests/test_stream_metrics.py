"""TTFT / total-duration measurement, made deterministic with an injected fake monotonic clock."""

import asyncio
import logging
import re
import time

from app.chat_service import ChatService
from app.main import create_app
from tests.asgi_client import Call, wait_until
from tests.conftest import FakeProvider, make_settings


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 15))


def build(provider, clock, **settings):
    app = create_app(make_settings(**settings), llm_provider=provider)
    app.state.chat_service._clock = clock  # the service measures with this clock
    return app


def latency_provider(clock, chunks, first=0.25, each=0.1, **kwargs):
    """Gemini 'thinks' for `first` seconds, then produces a chunk every `each` seconds."""
    return FakeProvider(chunks=chunks, on_chunk=lambda i: clock.advance(first if i == 0 else each), **kwargs)


def test_default_clock_is_monotonic():
    app = create_app(make_settings(), llm_provider=FakeProvider())
    assert app.state.chat_service._clock is time.monotonic  # wall-clock jumps (NTP, DST) cannot distort timings
    assert isinstance(app.state.chat_service, ChatService)


def test_ttft_and_total_duration_are_reported_in_the_done_event():
    clock = FakeClock()
    provider = latency_provider(clock, ["a ", "b ", "c ", "d"])

    async def scenario():
        call = Call(build(provider, clock), {"message": "hi", "session_id": "s"})
        await call.read_start()
        events = await call.events()
        await call.finished()
        return events[-1]

    name, done = run(scenario())
    assert name == "done"
    assert done["ttft_ms"] == 250.0  # request start -> first chunk
    assert done["total_ms"] == 550.0  # 250 + 3 * 100
    assert done["chunks"] == 4


def test_ttft_includes_time_spent_waiting_for_the_session():
    clock = FakeClock()
    gate = asyncio.Event()
    provider = FakeProvider(chunks=["a "], chunk_gates=[gate], on_chunk=lambda i: clock.advance(0.25))

    async def scenario():
        app = build(provider, clock)
        first = Call(app, {"message": "one", "session_id": "s"})
        await wait_until(lambda: provider.streams_started == 1)
        second = Call(app, {"message": "two", "session_id": "s"})  # queued behind the same session
        await asyncio.sleep(0.05)
        clock.advance(2.0)  # two seconds pass while it waits
        gate.set()
        await first.read_start(); await first.events(); await first.finished()
        await second.read_start()
        events = await second.events()
        await second.finished()
        return events[-1][1]

    done = run(scenario())
    assert done["ttft_ms"] == 2500.0  # 2.0 s waiting + 0.25 s (first request) + 0.25 s thinking


def test_metrics_line_is_logged_with_timings_and_no_content(caplog):
    clock = FakeClock()
    provider = latency_provider(clock, ["PRIVATE-a ", "PRIVATE-b"])

    async def scenario():
        app = build(provider, clock)
        caplog.set_level(logging.DEBUG)
        call = Call(app, {"message": "PRIVATE-prompt", "session_id": "private-session"})
        await call.read_start(); await call.events(); await call.finished()

    run(scenario())
    line = next(l for l in caplog.text.splitlines() if "stream finished" in l)
    assert re.search(r"outcome=completed error=- model=fake-model queue_ms=0 ttft_ms=250 total_ms=350 chunks=2", line)
    for forbidden in ("PRIVATE", "private-session"):
        assert forbidden not in caplog.text


def test_failed_stream_reports_ttft_only_if_a_chunk_arrived():
    from app.errors import LLMProviderError

    clock = FakeClock()
    cases = {0: "ttft_ms=-", 1: "ttft_ms=250"}  # error before / after the first chunk

    for error_after, expected in cases.items():
        provider = latency_provider(clock, ["a ", "b"], stream_error=LLMProviderError(), error_after=error_after)

        async def scenario():
            app = build(provider, clock)
            call = Call(app, {"message": "hi", "session_id": "s"})
            await call.read_start()
            await (call.events() if call.status == 200 else call.json_body())
            await call.finished()

        import logging as _logging
        records = []
        handler = _logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        _logging.getLogger("app.chat_service").addHandler(handler)
        try:
            run(scenario())
        finally:
            _logging.getLogger("app.chat_service").removeHandler(handler)
        finished = [m for m in records if "stream finished" in m]
        assert finished and "outcome=failed" in finished[0] and expected in finished[0], finished
