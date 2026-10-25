"""Chat use cases (blocking and streaming): session history + system instruction + provider call.

No HTTP or SDK details here. Lock order is always: session lock first, then a generation slot, so a request that
is merely waiting for a busy session never occupies one of the limited Gemini slots.
"""

import asyncio
import logging
import time
import traceback
from collections.abc import AsyncIterator, Callable

from app.config import Settings
from app.errors import AppError, LLMBadResponseError, LLMNotConfiguredError, LLMTimeoutError
from app.limits import GenerationLimiter
from app.llm.base import ChatMessage, LLMProvider
from app.prompts import build_system_instruction
from app.sessions import SessionStore
from app.streaming import DoneEvent, StartEvent, StreamEvent, TokenEvent

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(
        self,
        provider: LLMProvider | None,
        store: SessionStore,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,  # monotonic: immune to wall-clock changes; injectable for tests
    ) -> None:
        self._provider = provider  # None when no API key is configured
        self._store = store
        self._clock = clock
        self._lock_timeout = settings.session_lock_timeout_seconds
        self._idle_timeout = settings.llm_timeout_seconds  # longest wait for the next stream chunk
        self._stream_timeout = settings.llm_stream_timeout_seconds  # longest whole streamed generation
        self.limiter = GenerationLimiter(settings.llm_max_concurrent_generations, settings.generation_queue_timeout_seconds)

    @property
    def model(self) -> str | None:
        return self._provider.model if self._provider else None

    @property
    def stream_send_timeout(self) -> float:
        """How long a client may take to accept one event before the stream is dropped."""
        return self._idle_timeout

    # ------------------------------------------------------------------ blocking chat (Phase 2)

    async def chat(
        self, *, message: str, session_id: str, language: str, agent_prompt: str | None = None
    ) -> str:
        if self._provider is None:
            raise LLMNotConfiguredError()  # checked first: no session is created for a request we cannot serve

        async with self._store.locked(session_id, self._lock_timeout) as session:
            prompt_to_use = agent_prompt or session.system_prompt
            system_instruction = build_system_instruction(language, agent_prompt=prompt_to_use)
            messages = [*session.messages(), ChatMessage("user", message)]
            async with self.limiter.slot():
                started = self._clock()
                reply = await self._provider.generate(system_instruction=system_instruction, messages=messages)
                latency_ms = (self._clock() - started) * 1000
            # Only a successful exchange is remembered: a failed call leaves the history untouched.
            session.append_turn(message, reply)

        # Metadata only. Never log the message, the reply or the session id.
        logger.info("chat ok: model=%s latency_ms=%.0f history_messages=%d", self.model, latency_ms, len(messages) + 1)
        return reply

    # ------------------------------------------------------------------ streaming chat (Phase 3A)

    async def stream(
        self,
        *,
        message: str,
        session_id: str,
        language: str,
        request_id: str | None = None,
        agent_prompt: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Yield StartEvent, TokenEvent... DoneEvent, or raise before the first yield / after some tokens.

        Resources (session lock, generation slot, upstream stream) are acquired when iteration starts and are
        released by the `finally`/`async with` blocks below whenever the generator ends or is closed/cancelled.
        The assistant reply is added to the session history only after the provider stream finished successfully:
        a failed, timed-out or cancelled generation leaves the history exactly as it was.
        """
        if self._provider is None:
            raise LLMNotConfiguredError()

        loop = asyncio.get_running_loop()
        started = self._clock()  # request start (monotonic)
        outcome, error_code = "cancelled", None  # stays "cancelled" if we are closed/cancelled before finishing
        ttft_ms: float | None = None
        queue_ms = 0.0
        chunks = 0
        try:
            async with self._store.locked(session_id, self._lock_timeout) as session:
                async with self.limiter.slot():
                    queue_ms = (self._clock() - started) * 1000
                    messages = [*session.messages(), ChatMessage("user", message)]
                    deadline = loop.time() + self._stream_timeout
                    prompt_to_use = agent_prompt or session.system_prompt
                    source = self._provider.stream(
                        system_instruction=build_system_instruction(language, agent_prompt=prompt_to_use),
                        messages=messages,
                    )
                    parts: list[str] = []
                    try:
                        while True:
                            remaining = deadline - loop.time()
                            if remaining <= 0:
                                raise LLMTimeoutError()
                            try:
                                async with asyncio.timeout(min(self._idle_timeout, remaining)):
                                    text = await anext(source)
                            except StopAsyncIteration:
                                break
                            except TimeoutError:
                                raise LLMTimeoutError() from None

                            if not parts:
                                if not text.strip():
                                    continue  # leading blank chunks carry nothing worth starting a response for
                                text = text.lstrip()
                                ttft_ms = (self._clock() - started) * 1000
                                yield StartEvent(session_id, self._provider.model, request_id)
                            parts.append(text)
                            chunks += 1
                            yield TokenEvent(text)

                        if not parts:
                            raise LLMBadResponseError()  # the provider produced no text at all
                        session.append_turn(message, "".join(parts).strip())  # commit ONLY after full success
                        total_ms = (self._clock() - started) * 1000
                        outcome = "completed"
                        yield DoneEvent(session_id, self._provider.model, round(ttft_ms, 1), round(total_ms, 1), chunks)
                    finally:
                        await self._close_source(source)
        except LLMTimeoutError as exc:
            outcome, error_code = "timeout", exc.code
            raise
        except AppError as exc:
            outcome, error_code = "failed", exc.code
            raise
        except Exception as exc:
            outcome, error_code = "failed", "internal_error"
            # Exception type + traceback FRAMES (where it happened), but never the exception message, which could
            # contain prompt or response text.
            logger.error(
                "Unexpected error while streaming [request %s]: %s\n%s",
                request_id, type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__)),
            )
            raise
        finally:
            # One privacy-safe line per stream: timings and outcome only. No prompt, reply, session id or key.
            total_ms = (self._clock() - started) * 1000
            logger.log(
                logging.INFO if outcome in ("completed", "cancelled") else logging.WARNING,
                "stream finished: outcome=%s error=%s model=%s queue_ms=%.0f ttft_ms=%s total_ms=%.0f chunks=%d",
                outcome, error_code or "-", self.model, queue_ms,
                "-" if ttft_ms is None else f"{ttft_ms:.0f}", total_ms, chunks,
            )

    @staticmethod
    async def _close_source(source: AsyncIterator[str]) -> None:
        """Stop the provider stream (and with it the upstream request). Runs on success, error and cancellation."""
        aclose = getattr(source, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                logger.debug("closing the provider stream failed", exc_info=False)

    async def aclose(self) -> None:
        if self._provider is not None:
            await self._provider.aclose()
