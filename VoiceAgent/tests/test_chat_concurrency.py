"""Concurrent /chat requests: same-session serialisation, cross-session parallelism, cancellation."""

import asyncio

import httpx

from app.llm.base import ChatMessage
from app.main import create_app
from tests.conftest import FakeProvider, make_settings


def run_scenario(scenario, provider, **settings_overrides):
    """Run `scenario(http)` against an in-process app (all requests share one event loop, like production)."""
    app = create_app(make_settings(**settings_overrides), llm_provider=provider)

    async def main():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
            # Hard cap: if a regression deadlocks the service, fail in 10 s instead of hanging the whole suite.
            return await asyncio.wait_for(scenario(http), timeout=10)

    return asyncio.run(main())


async def wait_until(predicate, timeout=3.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition not reached in time"
        await asyncio.sleep(0.01)


def chat(http, message, session_id):
    return http.post("/chat", json={"message": message, "session_id": session_id})


def test_same_session_requests_are_serialised_and_history_stays_consistent():
    gate = asyncio.Event()
    provider = FakeProvider(gate=gate)

    async def scenario(http):
        first = asyncio.create_task(chat(http, "first", "s"))
        await wait_until(lambda: len(provider.calls) == 1)
        second = asyncio.create_task(chat(http, "second", "s"))
        await asyncio.sleep(0.1)
        assert len(provider.calls) == 1, "second request must wait for the session lock, not run in parallel"
        gate.set()
        return await asyncio.gather(first, second)

    r1, r2 = run_scenario(scenario, provider)
    assert r1.status_code == r2.status_code == 200
    assert provider.max_in_flight == 1
    assert provider.calls[1][1] == [
        ChatMessage("user", "first"), ChatMessage("assistant", "fake-reply-1"), ChatMessage("user", "second"),
    ]


def test_many_concurrent_requests_to_one_session_do_not_corrupt_history():
    provider = FakeProvider()
    count = 30

    async def scenario(http):
        responses = await asyncio.gather(*(chat(http, f"msg-{i}", "shared") for i in range(count)))
        final = await chat(http, "final", "shared")
        return responses, final

    responses, final = run_scenario(scenario, provider, session_max_turns=100)
    assert all(r.status_code == 200 for r in responses) and final.status_code == 200
    assert provider.max_in_flight == 1  # strictly one at a time for a session
    messages = provider.calls[-1][1]
    assert len(messages) == 2 * count + 1
    roles = [m.role for m in messages]
    assert roles == ["user", "assistant"] * count + ["user"]  # strictly alternating: no interleaving
    users = [m.text for m in messages if m.role == "user"][:-1]
    assert sorted(users) == sorted(f"msg-{i}" for i in range(count))  # every message recorded exactly once
    replies = [m.text for m in messages if m.role == "assistant"]
    assert len(set(replies)) == count  # each reply stored once, paired with the right turn


def test_different_sessions_run_in_parallel_and_stay_isolated():
    gate = asyncio.Event()
    provider = FakeProvider(gate=gate)

    async def scenario(http):
        a = asyncio.create_task(chat(http, "from A", "session-a"))
        b = asyncio.create_task(chat(http, "from B", "session-b"))
        await wait_until(lambda: provider.in_flight == 2)  # both reached the provider at the same time
        gate.set()
        return await asyncio.gather(a, b)

    ra, rb = run_scenario(scenario, provider)
    assert ra.status_code == rb.status_code == 200
    assert provider.max_in_flight == 2
    for _, messages in provider.calls:
        assert len(messages) == 1  # neither saw the other's text


def test_busy_session_returns_409_after_lock_timeout():
    gate = asyncio.Event()
    provider = FakeProvider(gate=gate)

    async def scenario(http):
        first = asyncio.create_task(chat(http, "slow", "s"))
        await wait_until(lambda: len(provider.calls) == 1)
        busy = await chat(http, "impatient", "s")
        gate.set()
        return busy, await first

    busy, first = run_scenario(scenario, provider, session_lock_timeout_seconds=0.1)
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "session_busy"
    assert first.status_code == 200
    assert len(provider.calls) == 1  # the impatient request never reached the model


def test_capacity_reached_when_every_session_is_mid_request():
    gate = asyncio.Event()
    provider = FakeProvider(gate=gate)

    async def scenario(http):
        first = asyncio.create_task(chat(http, "running", "only-session"))
        await wait_until(lambda: len(provider.calls) == 1)
        rejected = await chat(http, "new conversation", "another-session")
        gate.set()
        return rejected, await first

    rejected, first = run_scenario(scenario, provider, session_max_sessions=1)
    assert rejected.status_code == 503 and rejected.json()["error"]["code"] == "session_capacity_reached"
    assert first.status_code == 200


def test_cancelled_request_releases_the_session():
    gate = asyncio.Event()
    provider = FakeProvider(gate=gate)

    async def scenario(http):
        stuck = asyncio.create_task(chat(http, "will be cancelled", "s"))
        await wait_until(lambda: len(provider.calls) == 1)
        stuck.cancel()  # e.g. the caller gave up
        await asyncio.gather(stuck, return_exceptions=True)
        gate.set()
        return await asyncio.wait_for(chat(http, "after cancel", "s"), timeout=3)

    response = run_scenario(scenario, provider)
    assert response.status_code == 200  # the lock was released, the session is not stuck
    assert provider.in_flight == 0
    # the cancelled turn was never stored
    assert provider.calls[-1][1] == [ChatMessage("user", "after cancel")]
