"""SessionStore unit tests: bounds, expiry, eviction and locking, using a fake clock (no real waiting)."""

import asyncio

import pytest

from app.errors import SessionBusyError, SessionLimitError
from app.llm.base import ChatMessage
from app.sessions import SessionStore


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_store(clock=None, **overrides):
    values = dict(max_sessions=100, ttl_seconds=60, max_turns=10, max_history_chars=10_000)
    values.update(overrides)
    return SessionStore(clock=clock or Clock(), **values)


async def touch(store, sid, user="u", assistant="a"):
    async with store.locked(sid, 1) as session:
        session.append_turn(user, assistant)


def history(store, sid):
    async def read():
        async with store.locked(sid, 1) as session:
            return session.messages()

    return asyncio.run(read())


# ---------------------------------------------------------------- history bounds

def test_turns_are_recorded_in_order():
    store = make_store()
    asyncio.run(touch(store, "s", "hello", "hi"))
    asyncio.run(touch(store, "s", "bye", "ciao"))
    assert history(store, "s") == [
        ChatMessage("user", "hello"), ChatMessage("assistant", "hi"),
        ChatMessage("user", "bye"), ChatMessage("assistant", "ciao"),
    ]


def test_turn_limit_drops_oldest_turns_first():
    store = make_store(max_turns=3)

    async def run():
        for i in range(10):
            await touch(store, "s", f"u{i}", f"a{i}")

    asyncio.run(run())
    assert [m.text for m in history(store, "s")] == ["u7", "a7", "u8", "a8", "u9", "a9"]


def test_character_limit_drops_oldest_turns_first():
    store = make_store(max_history_chars=100)

    async def run():
        for i in range(10):
            await touch(store, "s", f"{i}" * 30, f"{i}" * 30)  # 60 chars per turn

    asyncio.run(run())
    texts = [m.text for m in history(store, "s")]
    assert sum(len(t) for t in texts) <= 100
    assert texts[-1] == "9" * 30  # the newest turn is always kept


def test_a_single_oversized_turn_is_still_kept():
    store = make_store(max_history_chars=10)
    asyncio.run(touch(store, "s", "x" * 500, "y" * 500))
    assert len(history(store, "s")) == 2  # never trimmed to nothing mid-conversation


def test_messages_returns_a_copy():
    store = make_store()
    asyncio.run(touch(store, "s"))

    async def run():
        async with store.locked("s", 1) as session:
            session.messages().clear()
            return session.messages()

    assert len(asyncio.run(run())) == 2


# ---------------------------------------------------------------- expiry

def test_idle_session_expires_and_context_is_reset():
    clock = Clock()
    store = make_store(clock, ttl_seconds=60)
    asyncio.run(touch(store, "s", "remember me", "ok"))
    clock.now += 61
    assert history(store, "s") == []  # expired: a brand-new session


def test_session_within_ttl_is_kept():
    clock = Clock()
    store = make_store(clock, ttl_seconds=60)
    asyncio.run(touch(store, "s", "remember me", "ok"))
    clock.now += 59
    assert len(history(store, "s")) == 2


def test_activity_extends_the_ttl():
    clock = Clock()
    store = make_store(clock, ttl_seconds=60)
    asyncio.run(touch(store, "s"))
    for _ in range(5):
        clock.now += 50
        asyncio.run(touch(store, "s"))  # still active: total elapsed 250 s > ttl, but never idle for 60 s
    assert len(history(store, "s")) == 12


def test_expired_sessions_are_purged_from_memory():
    clock = Clock()
    store = make_store(clock, ttl_seconds=60)
    for i in range(20):
        asyncio.run(touch(store, f"s{i}"))
    assert len(store) == 20
    clock.now += 61
    asyncio.run(touch(store, "fresh"))
    assert len(store) == 1


# ---------------------------------------------------------------- capacity / LRU eviction

def test_least_recently_used_session_is_evicted_at_capacity():
    clock = Clock()
    store = make_store(clock, max_sessions=3)

    async def run():
        for sid in ("a", "b", "c"):
            clock.now += 1
            await touch(store, sid, f"user-{sid}")
        clock.now += 1
        await touch(store, "a", "again")  # "a" becomes most recently used; "b" is now the oldest
        clock.now += 1
        await touch(store, "d")  # over capacity: "b" must go

    asyncio.run(run())
    assert len(store) == 3
    assert history(store, "b") == []  # evicted (and recreated empty just now)
    assert history(store, "a") != []


def test_memory_stays_bounded_under_many_sessions():
    store = make_store(max_sessions=50)

    async def run():
        for i in range(500):
            await touch(store, f"s{i}")

    asyncio.run(run())
    assert len(store) <= 50


def test_active_session_is_never_evicted_and_capacity_error_when_all_busy():
    async def run():
        store = make_store(max_sessions=1)
        async with store.locked("busy", 1):  # mid-request
            with pytest.raises(SessionLimitError):
                async with store.locked("other", 0.1):
                    pass
            assert len(store) == 1
        async with store.locked("other", 1):  # once the first finished it can be evicted
            pass

    asyncio.run(run())


def test_purge_never_removes_a_session_that_is_mid_request():
    async def run():
        clock = Clock()
        store = make_store(clock, ttl_seconds=60)
        async with store.locked("long-running", 1) as session:
            session.append_turn("u", "a")
            clock.now += 500  # far beyond the ttl while the request is still running
            async with store.locked("another", 1):
                pass
        return len(store)

    assert asyncio.run(run()) == 2


# ---------------------------------------------------------------- locking

def test_second_request_for_same_session_waits_for_the_first():
    async def run():
        store = make_store()
        order = []

        async def worker(name, hold):
            async with store.locked("s", 5):
                order.append(f"{name}-start")
                await asyncio.sleep(hold)
                order.append(f"{name}-end")

        await asyncio.gather(worker("A", 0.05), worker("B", 0))
        return order

    # B never starts before A has finished
    assert asyncio.run(run()) == ["A-start", "A-end", "B-start", "B-end"]


def test_busy_session_raises_after_lock_timeout():
    async def run():
        store = make_store()
        async with store.locked("s", 1):
            with pytest.raises(SessionBusyError):
                async with store.locked("s", 0.05):
                    pass

    asyncio.run(run())


def test_lock_is_released_when_the_request_fails():
    async def run():
        store = make_store()
        with pytest.raises(RuntimeError):
            async with store.locked("s", 1):
                raise RuntimeError("provider blew up")
        async with store.locked("s", 0.1):  # must not be stuck
            return True

    assert asyncio.run(run())


def test_different_sessions_do_not_block_each_other():
    async def run():
        store = make_store()
        async with store.locked("one", 1):
            async with store.locked("two", 0.05):
                return True

    assert asyncio.run(run())
