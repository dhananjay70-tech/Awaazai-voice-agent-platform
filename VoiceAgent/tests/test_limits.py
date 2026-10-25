"""GenerationLimiter: bounded concurrency with no slot leaks, plus the streaming/concurrency settings."""

import asyncio

import pytest
from pydantic import ValidationError

from app.errors import GenerationCapacityError
from app.limits import GenerationLimiter
from tests.conftest import make_settings


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 10))


def test_slots_are_limited_and_counted():
    async def scenario():
        limiter = GenerationLimiter(2, 0.05)
        async with limiter.slot():
            async with limiter.slot():
                assert limiter.in_use == 2
                with pytest.raises(GenerationCapacityError):
                    async with limiter.slot():
                        pass
                assert limiter.in_use == 2  # the rejected attempt did not take or leak a slot
            assert limiter.in_use == 1
        assert limiter.in_use == 0

    run(scenario())


def test_slot_released_when_the_body_raises():
    async def scenario():
        limiter = GenerationLimiter(1, 0.05)
        for _ in range(10):
            with pytest.raises(RuntimeError):
                async with limiter.slot():
                    raise RuntimeError("boom")
        assert limiter.in_use == 0
        async with limiter.slot():  # the single slot is still available
            pass

    run(scenario())


def test_slot_released_when_the_holder_is_cancelled():
    async def scenario():
        limiter = GenerationLimiter(1, 0.5)
        started = asyncio.Event()

        async def hold():
            async with limiter.slot():
                started.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(hold())
        await started.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert limiter.in_use == 0
        async with limiter.slot():
            pass

    run(scenario())


def test_a_waiter_gets_the_slot_when_it_is_freed():
    async def scenario():
        limiter = GenerationLimiter(1, 2.0)
        order = []

        async def worker(name, hold):
            async with limiter.slot():
                order.append(f"{name}-in")
                await asyncio.sleep(hold)
            order.append(f"{name}-out")

        await asyncio.gather(worker("A", 0.05), worker("B", 0))
        assert order == ["A-in", "A-out", "B-in", "B-out"]
        assert limiter.in_use == 0

    run(scenario())


def test_cancelling_a_waiting_request_does_not_consume_a_slot():
    async def scenario():
        limiter = GenerationLimiter(1, 5.0)
        release = asyncio.Event()

        async def holder():
            async with limiter.slot():
                await release.wait()

        async def waiter():
            async with limiter.slot():
                pass

        hold = asyncio.create_task(holder())
        await asyncio.sleep(0.02)
        waiting = [asyncio.create_task(waiter()) for _ in range(5)]
        await asyncio.sleep(0.02)
        for task in waiting:
            task.cancel()
        await asyncio.gather(*waiting, return_exceptions=True)
        release.set()
        await hold
        assert limiter.in_use == 0
        async with limiter.slot():  # no permit was lost to the cancelled waiters
            pass

    run(scenario())


def test_many_cycles_do_not_leak():
    async def scenario():
        limiter = GenerationLimiter(3, 30.0)  # generous queue limit: Windows timers tick at ~15 ms, so 60 tasks take a while

        async def one(i):
            try:
                async with limiter.slot():
                    await asyncio.sleep(0.001)
                    if i % 7 == 0:
                        raise ValueError
            except ValueError:
                pass

        await asyncio.gather(*(one(i) for i in range(60)))
        assert limiter.in_use == 0
        async with limiter.slot(), limiter.slot(), limiter.slot():  # all 3 permits intact
            assert limiter.in_use == 3

    run(scenario())


class TestSettings:
    def test_defaults_are_safe(self):
        settings = make_settings()
        assert settings.llm_stream_timeout_seconds == 60
        assert 1 <= settings.llm_max_concurrent_generations <= 200
        assert 0 < settings.generation_queue_timeout_seconds <= 60

    def test_environment_overrides(self, monkeypatch):
        monkeypatch.setenv("LLM_STREAM_TIMEOUT_SECONDS", "30")
        monkeypatch.setenv("LLM_MAX_CONCURRENT_GENERATIONS", "3")
        monkeypatch.setenv("GENERATION_QUEUE_TIMEOUT_SECONDS", "2")
        settings = make_settings()
        assert (settings.llm_stream_timeout_seconds, settings.llm_max_concurrent_generations, settings.generation_queue_timeout_seconds) == (30, 3, 2)

    @pytest.mark.parametrize(
        "override",
        [
            {"llm_stream_timeout_seconds": 0}, {"llm_stream_timeout_seconds": 601},
            {"llm_max_concurrent_generations": 0}, {"llm_max_concurrent_generations": 201},
            {"generation_queue_timeout_seconds": 0}, {"generation_queue_timeout_seconds": 61},
        ],
    )
    def test_invalid_values_are_rejected(self, override):
        with pytest.raises(ValidationError):
            make_settings(**override)
