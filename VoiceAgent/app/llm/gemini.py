"""Gemini implementation of LLMProvider, using the official google-genai SDK (async API).

Security: provider error *messages* are never logged or returned (they can echo request details). Only the
failure category and the numeric HTTP code are logged. The API key is only handed to the SDK client.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.errors import (
    AppError,
    LLMAuthError,
    LLMBadResponseError,
    LLMModelUnavailableError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.base import ChatMessage

logger = logging.getLogger(__name__)

_ROLE_MAP = {"user": "user", "assistant": "model"}  # Gemini calls the assistant role "model"
_END = object()  # marks the normal end of a stream in the producer -> consumer queue
_MAX_BUFFERED_CHUNKS = 2048  # far above one reply (bounded by max_output_tokens); stops a stuck consumer growing memory


class GeminiProvider:
    _TIMEOUT_MARGIN_SECONDS = 2.0  # asyncio safety net = SDK timeout + this margin

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        temperature: float,
        max_output_tokens: int,
        client: Any | None = None,  # tests inject a fake; production builds the real SDK client
    ) -> None:
        self.model = model
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),  # SDK timeout is in milliseconds
        )

    def _build_request(self, system_instruction: str, messages: Sequence[ChatMessage]):
        contents = [
            types.Content(role=_ROLE_MAP[m.role], parts=[types.Part(text=m.text)]) for m in messages
        ]
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=self._temperature,
            max_output_tokens=self._max_output_tokens,
            # Voice replies must be fast: skip the model's hidden "thinking" step (it also consumes output tokens).
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        return contents, config

    async def generate(self, *, system_instruction: str, messages: Sequence[ChatMessage]) -> str:
        contents, config = self._build_request(system_instruction, messages)
        try:
            # Belt and braces: the SDK has its own HTTP timeout, this also bounds anything else it awaits.
            async with asyncio.timeout(self._timeout_seconds + self._TIMEOUT_MARGIN_SECONDS):
                response = await self._client.aio.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
        except asyncio.CancelledError:
            raise  # a cancelled request must stop, not be turned into an error response
        except Exception as exc:
            raise self._translate(exc) from None  # `from None`: never chain the raw provider error

        return self._extract_text(response)

    async def stream(self, *, system_instruction: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        """Yield text chunks as Gemini produces them (SDK: `await aio.models.generate_content_stream(...)`).

        The SDK iteration runs in its OWN producer task and chunks reach this generator through a queue. That is
        deliberate: verified against a real streaming server (tests/test_sdk_stream_cancellation.py), the SDK only
        closes the upstream HTTP connection when a network read is cancelled. Closing its (nested, suspended)
        async generators with aclose() leaves the connection open. The producer is never suspended anywhere except
        inside the network read, so cancelling it (which we do whenever this generator ends, is closed, or is
        cancelled) always closes the connection and Gemini is no longer read for a client that has gone.
        """
        contents, config = self._build_request(system_instruction, messages)
        queue: asyncio.Queue = asyncio.Queue()
        producer = asyncio.create_task(self._produce(contents, config, queue), name="gemini-stream-producer")
        try:
            while True:
                item = await queue.get()
                if item is _END:
                    return
                if isinstance(item, BaseException):
                    raise item  # already translated to one of our safe error types
                yield item
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)  # returns once the SDK stream is torn down

    async def _produce(self, contents: Any, config: Any, queue: asyncio.Queue) -> None:
        """Read the SDK stream and hand text chunks to the consumer. Never awaits anything but the network."""
        sdk_stream = None
        produced = False
        last_chunk = None
        try:
            sdk_stream = await self._client.aio.models.generate_content_stream(
                model=self.model, contents=contents, config=config
            )
            async for chunk in sdk_stream:
                last_chunk = chunk
                text = getattr(chunk, "text", None)
                if isinstance(text, str) and text:
                    if text.strip():
                        produced = True  # a reply of only whitespace is as empty as no reply (same rule as generate())
                    if queue.qsize() >= _MAX_BUFFERED_CHUNKS:  # the consumer is not draining: refuse unbounded growth
                        logger.warning("Gemini stream abandoned: consumer is not keeping up")
                        raise LLMProviderError()
                    queue.put_nowait(text)  # synchronous: the producer is never paused between chunks
            if not produced:
                self._log_empty_reason(last_chunk)
                raise LLMBadResponseError()
            queue.put_nowait(_END)
        except asyncio.CancelledError:
            raise  # the normal way a stream is stopped
        except AppError as exc:
            queue.put_nowait(exc)
        except Exception as exc:
            queue.put_nowait(self._translate(exc))  # provider details are dropped here, never queued
        finally:
            await self._close_sdk_stream(sdk_stream)

    @staticmethod
    async def _close_sdk_stream(sdk_stream: Any) -> None:
        aclose = getattr(sdk_stream, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:  # best effort: the stream is being abandoned anyway
                logger.debug("closing the Gemini stream failed", exc_info=False)

    async def aclose(self) -> None:
        try:
            await self._client.aio.aclose()
        except Exception:  # shutting down: nothing useful to do with a close failure
            logger.debug("Gemini client close failed", exc_info=False)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _extract_text(response: Any) -> str:
        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        GeminiProvider._log_empty_reason(response)
        raise LLMBadResponseError()

    @staticmethod
    def _log_empty_reason(response: Any) -> None:
        # Empty reply: record WHY (category only, no content) so operators can tell a safety block from a glitch.
        feedback = getattr(response, "prompt_feedback", None)
        candidates = getattr(response, "candidates", None) or []
        if getattr(feedback, "block_reason", None):
            reason = "prompt_blocked"
        elif candidates:
            reason = f"finish_{getattr(getattr(candidates[0], 'finish_reason', None), 'name', 'unknown').lower()}"
        else:
            reason = "no_candidates"
        logger.warning("Gemini returned no usable text: reason=%s", reason)

    @staticmethod
    def _translate(exc: Exception):
        """Map any SDK/network failure to one of our safe error types."""
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
            category, error = "timeout", LLMTimeoutError()
        elif isinstance(exc, genai_errors.APIError):
            code = getattr(exc, "code", None)
            status = str(getattr(exc, "status", "") or "")
            message = str(getattr(exc, "message", "") or "").lower()
            if code in (401, 403) or (code == 400 and ("api key" in message or "API_KEY" in status)):
                category, error = "auth", LLMAuthError()
            elif code == 429:
                category, error = "rate_limit", LLMRateLimitError()
            elif code == 404:  # unknown, retired or not-yet-enabled model name
                category, error = "model_unavailable", LLMModelUnavailableError()
            elif code in (408, 504):
                category, error = "timeout", LLMTimeoutError()
            elif isinstance(exc, genai_errors.ServerError):
                category, error = "server_error", LLMUnavailableError()
            else:
                category, error = "client_error", LLMProviderError()
            logger.warning("Gemini call failed: category=%s http_code=%s", category, code)
            return error
        elif isinstance(exc, (httpx.HTTPError, OSError)):
            category, error = "network", LLMUnavailableError()
        else:
            category, error = "unexpected", LLMProviderError()
            logger.warning("Gemini call failed: category=%s type=%s", category, type(exc).__name__)
            return error
        logger.warning("Gemini call failed: category=%s", category)
        return error
