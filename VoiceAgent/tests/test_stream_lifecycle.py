"""Cancellation, timeouts, stalled clients, lock/slot release, concurrency limits and task leaks for /chat/stream.

Every scenario runs under a hard wall-clock cap (see `run`), so a deadlock fails fast instead of hanging the suite.
"""

import asyncio
import logging

import pytest

from app.errors import LLMProviderError
from app.llm.base import ChatMessage
from app.main import create_app
from tests.asgi_client import Call, wait_until
from tests.conftest import FakeProvider, make_settings


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


def make_app(provider, **settings):
    return create_app(make_settings(**settings), llm_provider=provider)


def service_of(app):
    return app.state.chat_service


def session_locked(app, session_id) -> bool:
    session = service_of(app)._store._sessions.get(session_id)
    return bool(session and session.lock.locked())


async def assert_clean(app, provider, *, leaked_tasks_allowed: int = 0):
    """Nothing may be left behind: no slot, no lock, no running generation, no stray task."""
    await wait_until(lambda: service_of(app).limiter.in_use == 0 and provider.in_flight == 0)
    assert not any(s.lock.locked() for s in service_of(app)._store._sessions.values()), "session lock leaked"
    await asyncio.sleep(0.05)
    current = asyncio.current_task()
    stray = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    assert len(stray) <= leaked_tasks_allowed, f"leaked tasks: {[t.get_name() for t in stray]}"


# ---------------------------------------------------------------- 14. client disconnect / cancellation

def test_disconnect_mid_stream_cancels_upstream_and_releases_everything():
    provider = FakeProvider(chunks=["one ", "two ", "three"], hang_after=1)  # Gemini goes quiet after the first chunk

    async def scenario():
        app = make_app(provider)
        call = Call(app, {"message": "hi", "session_id": "s"})
        await call.read_start()
        await call.next_event()  # start
        await call.next_event()  # first token
        assert session_locked(app, "s") and service_of(app).limiter.in_use == 1

        call.disconnect()  # the browser tab was closed
        await call.finished()  # the ASGI app returns promptly

        assert provider.stream_cancelled, "upstream generation must be cancelled when the client goes away"
        assert provider.streams_closed == 1
        await assert_clean(app, provider)
        assert not session_locked(app, "s")

    run(scenario())


def test_cancelled_stream_is_not_added_to_history():
    provider = FakeProvider(chunks=["partial ", "answer"], hang_after=1)

    async def scenario():
        app = make_app(provider)
        call = Call(app, {"message": "interrupted question", "session_id": "s"})
        await call.read_start(); await call.next_event(); await call.next_event()
        call.disconnect(); await call.finished()

        provider.hang_after = None
        follow_up = Call(app, {"message": "next question", "session_id": "s"})
        await follow_up.read_start()
        await follow_up.events()
        await follow_up.finished()
        assert provider.calls[1][1] == [ChatMessage("user", "next question")]  # neither partial text nor lost question

    run(scenario())


def test_disconnect_before_the_first_chunk_cancels_upstream():
    gate = asyncio.Event()  # Gemini has not answered yet
    provider = FakeProvider(chunks=["late"], chunk_gates=[gate])

    async def scenario():
        app = make_app(provider)
        call = Call(app, {"message": "hi", "session_id": "s"})
        await wait_until(lambda: provider.streams_started == 1)
        call.disconnect()
        await call.finished()
        assert await call.read_start() == 499  # nothing was streamed; the app still answers the protocol
        assert provider.stream_cancelled and provider.chunks_sent == 0
        await assert_clean(app, provider)

    run(scenario())


def test_disconnect_while_waiting_for_a_busy_session_does_not_disturb_the_running_stream():
    gate = asyncio.Event()
    provider = FakeProvider(chunks=["a ", "b"], chunk_gates=[gate, gate])

    async def scenario():
        app = make_app(provider)
        first = Call(app, {"message": "first", "session_id": "s"})
        await wait_until(lambda: provider.streams_started == 1)
        second = Call(app, {"message": "second", "session_id": "s"})  # queued behind the same session
        await asyncio.sleep(0.05)
        second.disconnect()
        await second.finished()
        assert provider.streams_started == 1, "the queued request never reached Gemini"

        gate.set()
        await first.read_start()
        events = await first.events()
        assert events[-1][0] == "done"  # the first stream was unaffected
        await first.finished()
        await assert_clean(app, provider)

    run(scenario())


def test_repeated_connect_and_disconnect_leaks_nothing():
    provider = FakeProvider(chunks=["x "] * 5, hang_after=1)

    async def scenario():
        app = make_app(provider, llm_max_concurrent_generations=2, generation_queue_timeout_seconds=1)
        for i in range(25):
            call = Call(app, {"message": "hi", "session_id": f"s{i % 5}"})
            await call.read_start(); await call.next_event(); await call.next_event()
            call.disconnect()
            await call.finished()
        assert provider.streams_started == provider.streams_closed == 25
        await assert_clean(app, provider)
        # and the service still works afterwards
        provider.hang_after = None
        ok = Call(app, {"message": "still alive", "session_id": "fresh"})
        await ok.read_start()
        assert (await ok.events())[-1][0] == "done"

    run(scenario())


def test_cancelling_the_whole_request_task_cleans_up():
    """What the server does when a request is torn down (e.g. shutdown): cancel the ASGI task itself."""
    provider = FakeProvider(chunks=["one ", "two"], hang_after=1)

    async def scenario():
        app = make_app(provider)
        call = Call(app, {"message": "hi", "session_id": "s"})
        await call.read_start(); await call.next_event(); await call.next_event()
        call.task.cancel()
        await asyncio.gather(call.task, return_exceptions=True)
        assert provider.stream_cancelled
        await assert_clean(app, provider)

    run(scenario())


def test_service_finishes_the_providers_cleanup_before_releasing_the_session_and_slot():
    """Abandoning a stream must close the upstream FIRST, then free the lock and slot: not "eventually" via GC."""
    provider = FakeProvider(chunks=["one ", "two ", "three"], cleanup_delay=0.05)

    async def scenario():
        app = make_app(provider)
        service = service_of(app)
        events = service.stream(message="hi", session_id="s", language="english")
        assert type(await anext(events)).__name__ == "StartEvent"
        assert type(await anext(events)).__name__ == "TokenEvent"
        assert session_locked(app, "s") and service.limiter.in_use == 1

        await events.aclose()  # the consumer abandons the stream mid-answer
        assert provider.cleanup_done, "aclose() returned before the provider's upstream cleanup had finished"
        assert provider.stream_cancelled
        assert service.limiter.in_use == 0 and not session_locked(app, "s")

    run(scenario())


# ---------------------------------------------------------------- 13. timeouts

def test_idle_timeout_mid_stream_sends_error_event_and_cleans_up():
    provider = FakeProvider(chunks=["one ", "two"], hang_after=1)  # Gemini hangs after the first chunk

    async def scenario():
        app = make_app(provider, llm_timeout_seconds=0.15)
        call = Call(app, {"message": "hi", "session_id": "s"})
        await call.read_start()
        events = await call.events()
        assert [n for n, _ in events] == ["start", "token", "error"]
        assert events[-1][1]["code"] == "llm_timeout"
        await call.finished()
        assert provider.stream_cancelled
        await assert_clean(app, provider)

    run(scenario())


def test_timeout_before_the_first_chunk_is_a_504_json_error():
    provider = FakeProvider(chunks=["never"], chunk_gates=[asyncio.Event()])

    async def scenario():
        app = make_app(provider, llm_timeout_seconds=0.15)
        call = Call(app, {"message": "hi", "session_id": "s"})
        assert await call.read_start() == 504
        assert (await call.json_body())["error"]["code"] == "llm_timeout"
        await call.finished()
        assert provider.stream_cancelled
        await assert_clean(app, provider)

    run(scenario())


def test_whole_generation_timeout_stops_a_slow_trickle():
    # Each chunk arrives within the idle limit, but the answer as a whole takes too long.
    provider = FakeProvider(chunks=[f"w{i} " for i in range(50)], chunk_delay=0.05)

    async def scenario():
        app = make_app(provider, llm_timeout_seconds=5, llm_stream_timeout_seconds=0.3)
        call = Call(app, {"message": "hi", "session_id": "s"})
        await call.read_start()
        events = await call.events()
        assert events[-1][0] == "error" and events[-1][1]["code"] == "llm_timeout"
        assert 1 <= sum(1 for n, _ in events if n == "token") < 50
        await call.finished()
        assert provider.stream_cancelled and provider.chunks_sent < 50
        await assert_clean(app, provider)

    run(scenario())


def test_stalled_client_cannot_hold_the_session_forever():
    provider = FakeProvider(chunks=[f"w{i} " for i in range(100)])

    async def scenario():
        app = make_app(provider, llm_timeout_seconds=0.15)
        call = Call(app, {"message": "hi", "session_id": "s"}, stall_after_bodies=2)  # stops reading after 2 events
        await wait_until(lambda: provider.stream_cancelled)  # the server gives up on its own, within the send timeout
        assert provider.chunks_sent < 100  # and stops generating for a client that is not reading
        # Everything WE hold is released. (Only the transport-level send blocked on the stalled client remains:
        # that belongs to the web server, and is why one leftover task is expected here.)
        await assert_clean(app, provider, leaked_tasks_allowed=1)
        call.task.cancel()
        await asyncio.gather(call.task, return_exceptions=True)
        # the session is usable again straight away
        again = Call(app, {"message": "hello again", "session_id": "s"})
        await again.read_start()
        assert (await again.events())[-1][0] == "done"

    run(scenario())


# ---------------------------------------------------------------- 15. locks and limits released after errors

@pytest.mark.parametrize("error_after", [0, 1])
def test_lock_and_slot_are_released_after_provider_errors(error_after):
    provider = FakeProvider(chunks=["a ", "b "], stream_error=LLMProviderError(), error_after=error_after)

    async def scenario():
        app = make_app(provider, llm_max_concurrent_generations=1, generation_queue_timeout_seconds=0.5)
        for _ in range(5):  # a single slot: any leak would block (or 503) the next attempt
            call = Call(app, {"message": "hi", "session_id": "s"})
            await call.read_start()
            await call.events() if call.status == 200 else await call.json_body()
            await call.finished()
        assert provider.streams_started == provider.streams_closed == 5
        await assert_clean(app, provider)

    run(scenario())


def test_validation_errors_never_touch_locks_or_slots():
    provider = FakeProvider()

    async def scenario():
        app = make_app(provider, llm_max_concurrent_generations=1)
        for _ in range(5):
            call = Call(app, {"message": ""})
            assert await call.read_start() == 422
            await call.json_body(); await call.finished()
        assert service_of(app).limiter.in_use == 0 and provider.streams_started == 0

    run(scenario())


# ---------------------------------------------------------------- 8. same-session serialisation

def test_same_session_streams_are_serialised_and_history_is_consistent():
    gate = asyncio.Event()
    provider = FakeProvider(chunks=["first-reply "], chunk_gates=[gate])

    async def scenario():
        app = make_app(provider)
        first = Call(app, {"message": "first", "session_id": "s"})
        await wait_until(lambda: provider.streams_started == 1)
        second = Call(app, {"message": "second", "session_id": "s"})
        await asyncio.sleep(0.1)
        assert provider.streams_started == 1, "the second request must wait for the session lock"
        gate.set()
        await first.read_start(); await first.events(); await first.finished()
        await second.read_start(); await second.events(); await second.finished()
        assert provider.max_in_flight == 1
        assert provider.calls[1][1] == [
            ChatMessage("user", "first"), ChatMessage("assistant", "first-reply"), ChatMessage("user", "second"),
        ]

    run(scenario())


def test_many_concurrent_streams_on_one_session_keep_history_consistent():
    provider = FakeProvider()
    count = 20

    async def scenario():
        app = make_app(provider, session_max_turns=100, llm_max_concurrent_generations=4, session_lock_timeout_seconds=10)
        calls = [Call(app, {"message": f"msg-{i}", "session_id": "shared"}) for i in range(count)]
        for call in calls:
            await call.read_start()
            assert (await call.events())[-1][0] == "done"
            await call.finished()
        final = Call(app, {"message": "final", "session_id": "shared"})
        await final.read_start(); await final.events(); await final.finished()
        messages = provider.calls[-1][1]
        assert [m.role for m in messages] == ["user", "assistant"] * count + ["user"]  # strictly alternating
        assert sorted(m.text for m in messages if m.role == "user")[:-1] or True
        users = [m.text for m in messages if m.role == "user"][:-1]
        assert sorted(users) == sorted(f"msg-{i}" for i in range(count))  # each message exactly once
        assert provider.max_in_flight == 1

    run(scenario())


def test_busy_session_returns_409_after_the_lock_timeout():
    gate = asyncio.Event()
    provider = FakeProvider(chunks=["a"], chunk_gates=[gate])

    async def scenario():
        app = make_app(provider, session_lock_timeout_seconds=0.1)
        first = Call(app, {"message": "slow", "session_id": "s"})
        await wait_until(lambda: provider.streams_started == 1)
        second = Call(app, {"message": "impatient", "session_id": "s"})
        assert await second.read_start() == 409
        assert (await second.json_body())["error"]["code"] == "session_busy"
        gate.set()
        await first.read_start(); await first.events(); await first.finished(); await second.finished()
        await assert_clean(app, provider)

    run(scenario())


# ---------------------------------------------------------------- different sessions + concurrency limit

def test_different_sessions_stream_in_parallel_and_stay_isolated():
    gate = asyncio.Event()
    provider = FakeProvider(chunks=["x "], chunk_gates=[gate])

    async def scenario():
        app = make_app(provider)
        a = Call(app, {"message": "from A", "session_id": "a"})
        b = Call(app, {"message": "from B", "session_id": "b"})
        await wait_until(lambda: provider.in_flight == 2)  # both are generating at the same moment
        gate.set()
        for call in (a, b):
            await call.read_start(); assert (await call.events())[-1][0] == "done"; await call.finished()
        assert provider.max_in_flight == 2
        assert all(len(messages) == 1 for _, messages in provider.calls)

    run(scenario())


def test_concurrent_generations_are_bounded_and_excess_gets_503():
    gate = asyncio.Event()
    provider = FakeProvider(chunks=["x "], chunk_gates=[gate])

    async def scenario():
        app = make_app(provider, llm_max_concurrent_generations=2, generation_queue_timeout_seconds=0.15)
        running = [Call(app, {"message": "hi", "session_id": f"s{i}"}) for i in range(2)]
        await wait_until(lambda: provider.in_flight == 2)
        third = Call(app, {"message": "hi", "session_id": "s3"})
        assert await third.read_start() == 503
        assert (await third.json_body())["error"]["code"] == "generation_capacity_reached"
        assert provider.streams_started == 2 and provider.max_in_flight == 2

        gate.set()
        for call in running:
            await call.read_start(); await call.events(); await call.finished()
        fourth = Call(app, {"message": "hi", "session_id": "s4"})  # capacity is back
        assert await fourth.read_start() == 200
        await fourth.events(); await fourth.finished()
        await assert_clean(app, provider)

    run(scenario())


def test_stream_and_blocking_chat_share_one_concurrency_limit():
    gate = asyncio.Event()
    provider = FakeProvider(chunks=["x "], chunk_gates=[gate])

    async def scenario():
        app = make_app(provider, llm_max_concurrent_generations=1, generation_queue_timeout_seconds=0.15)
        stream_call = Call(app, {"message": "hi", "session_id": "s1"})
        await wait_until(lambda: provider.in_flight == 1)
        blocked = Call(app, {"message": "hi", "session_id": "s2"}, path="/chat")
        assert await blocked.read_start() == 503
        assert (await blocked.json_body())["error"]["code"] == "generation_capacity_reached"
        gate.set()
        await stream_call.read_start(); await stream_call.events(); await stream_call.finished()

    run(scenario())


def test_waiting_for_a_slot_does_not_hold_a_slot_or_deadlock():
    """A request queued behind a busy session must not occupy one of the limited Gemini slots."""
    gate = asyncio.Event()
    provider = FakeProvider(chunks=["x "], chunk_gates=[gate])

    async def scenario():
        app = make_app(provider, llm_max_concurrent_generations=1, generation_queue_timeout_seconds=0.5, session_lock_timeout_seconds=5)
        first = Call(app, {"message": "one", "session_id": "same"})
        await wait_until(lambda: provider.in_flight == 1)
        waiting = Call(app, {"message": "two", "session_id": "same"})  # waits for the SESSION, holds no slot
        await asyncio.sleep(0.1)
        assert service_of(app).limiter.in_use == 1  # only the first request's slot
        gate.set()
        for call in (first, waiting):
            await call.read_start(); await call.events(); await call.finished()
        await assert_clean(app, provider)

    run(scenario())


# ---------------------------------------------------------------- logging of outcomes

@pytest.mark.parametrize(
    "build, expected",
    [
        (lambda: dict(provider=FakeProvider(chunks=["a ", "b"], hang_after=1), settings=dict(llm_timeout_seconds=0.1)), "outcome=timeout"),
        (lambda: dict(provider=FakeProvider(chunks=["a ", "b"], stream_error=LLMProviderError(), error_after=1), settings={}), "outcome=failed error=llm_provider_error"),
        (lambda: dict(provider=FakeProvider(chunks=["a ", "b"]), settings={}), "outcome=completed"),
    ],
)
def test_outcome_is_logged_for_timeout_failure_and_success(build, expected, caplog):
    spec = build()

    async def scenario():
        app = make_app(spec["provider"], **spec["settings"])
        caplog.set_level(logging.DEBUG)
        call = Call(app, {"message": "hi", "session_id": "s"})
        await call.read_start(); await call.events(); await call.finished()

    run(scenario())
    assert expected in caplog.text


def test_cancelled_outcome_is_logged(caplog):
    provider = FakeProvider(chunks=["a ", "b"], hang_after=1)

    async def scenario():
        app = make_app(provider)
        caplog.set_level(logging.DEBUG)
        call = Call(app, {"message": "hi", "session_id": "s"})
        await call.read_start(); await call.next_event(); await call.next_event()
        call.disconnect(); await call.finished()
        await assert_clean(app, provider)

    run(scenario())
    assert "stream finished: outcome=cancelled" in caplog.text
