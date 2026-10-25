"""Bounds on simultaneous Gemini generations."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from app.errors import AppError, GenerationCapacityError


class GenerationLimiter:
    """At most `max_concurrent` generations run at once; extra requests wait briefly, then get a 503.

    One limiter is shared by /chat and /chat/stream, so the total number of in-flight Gemini calls is bounded.
    Use it as `async with limiter.slot():` so the slot is released on every path (success, error, cancellation).
    """

    def __init__(
        self,
        max_concurrent: int,
        queue_timeout_seconds: float,
        error_factory: Callable[[], AppError] = GenerationCapacityError,  # raised when no slot frees up in time
    ) -> None:
        self._error_factory = error_factory
        self.max_concurrent = max_concurrent
        self._queue_timeout = queue_timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._in_use = 0

    @property
    def in_use(self) -> int:
        return self._in_use

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        try:
            async with asyncio.timeout(self._queue_timeout):
                await self._semaphore.acquire()
        except TimeoutError:
            raise self._error_factory() from None
        self._in_use += 1
        try:
            yield
        finally:
            self._in_use -= 1
            self._semaphore.release()
