"""Server-Sent Events (SSE) for POST /chat/stream: event types, wire format and the response class.

Wire format (one blank line ends each event; data is always a single line of JSON):

    event: start   data: {"session_id", "model", "request_id"}
    event: token   data: {"text"}                     (many; sent as soon as Gemini produces them)
    event: done    data: {"session_id", "model", "ttft_ms", "total_ms", "chunks"}
    event: error   data: {"code", "message", "request_id"}   (replaces `done` if generation fails mid-stream)

The response does not begin (no headers, no `start`) until the first text chunk exists. Everything that can fail
before that point is therefore a normal JSON error with a real HTTP status, exactly like POST /chat.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, MutableMapping
from dataclasses import dataclass
from typing import Any

from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from app.errors import AppError

logger = logging.getLogger(__name__)

DISCONNECTED_BEFORE_START = 499  # nginx convention: "client closed request"; nobody is left to read it


@dataclass(frozen=True)
class StartEvent:
    session_id: str
    model: str
    request_id: str | None


@dataclass(frozen=True)
class TokenEvent:
    text: str


@dataclass(frozen=True)
class DoneEvent:
    session_id: str
    model: str
    ttft_ms: float
    total_ms: float
    chunks: int


StreamEvent = StartEvent | TokenEvent | DoneEvent


def format_sse(event: str, data: dict[str, Any]) -> bytes:
    # json.dumps never emits a raw newline, so the payload always fits on one `data:` line.
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def encode_event(event: StreamEvent) -> bytes:
    if isinstance(event, StartEvent):
        return format_sse("start", {"session_id": event.session_id, "model": event.model, "request_id": event.request_id})
    if isinstance(event, TokenEvent):
        return format_sse("token", {"text": event.text})
    return format_sse(
        "done",
        {
            "session_id": event.session_id,
            "model": event.model,
            "ttft_ms": event.ttft_ms,
            "total_ms": event.total_ms,
            "chunks": event.chunks,
        },
    )


class _ClientGone(Exception):
    """The client stopped reading (connection closed, or send failed)."""


class EventStreamResponse(Response):
    """Streams `events` as SSE and OWNS their cleanup.

    `events` is an async generator that holds the session lock, the concurrency slot and the upstream Gemini
    stream. It is only ever started from inside __call__, in a task that __call__ always cancels and awaits in a
    `finally`. So those resources are released on every path (finished, failed, client disconnect, timeout,
    cancellation of the request) and there is no window in which they are held but nobody will clean up.
    """

    media_type = "text/event-stream"

    def __init__(self, events: AsyncIterator[StreamEvent], *, request_id: str | None, send_timeout_seconds: float) -> None:
        super().__init__(content=None, status_code=200, media_type=self.media_type)
        self._events = events
        self._request_id = request_id
        self._send_timeout = send_timeout_seconds
        self._response_started = False
        self.raw_headers = [
            (b"content-type", b"text/event-stream; charset=utf-8"),
            (b"cache-control", b"no-cache, no-transform"),
            (b"x-accel-buffering", b"no"),  # tells nginx-style proxies not to buffer the stream
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        pump = asyncio.create_task(self._pump(send), name="sse-pump")
        watcher = asyncio.create_task(self._watch_disconnect(receive), name="sse-disconnect-watcher")
        try:
            await asyncio.wait({pump, watcher}, return_when=asyncio.FIRST_COMPLETED)
            if pump.done():
                pump.result()  # a failure BEFORE the response started propagates -> normal JSON error handlers
            else:
                # The client disconnected first. Nobody will read a response, but the ASGI app must still send one.
                await self._cancel(pump)
                if not self._response_started:
                    await send({"type": "http.response.start", "status": DISCONNECTED_BEFORE_START, "headers": []})
                    await send({"type": "http.response.body", "body": b""})
        finally:
            await self._cancel(pump, watcher)

    # ------------------------------------------------------------------ internals

    @staticmethod
    async def _cancel(*tasks: asyncio.Task) -> None:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)  # waits for the pump's `finally` to release everything

    @staticmethod
    async def _watch_disconnect(receive: Receive) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return

    async def _pump(self, send: Send) -> None:
        events = self._events
        try:
            first = await anext(events)  # may raise: nothing has been sent yet, so the caller still gets a real HTTP error
            await send({"type": "http.response.start", "status": 200, "headers": self.raw_headers})
            self._response_started = True
            try:
                await self._emit(send, encode_event(first))
                while True:
                    try:
                        event = await anext(events)
                    except StopAsyncIteration:
                        break
                    except Exception as exc:  # generation failed after the stream started
                        await self._emit_error(send, exc)
                        break
                    await self._emit(send, encode_event(event))
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            except _ClientGone:
                logger.debug("SSE client stopped reading; stream closed")
        finally:
            await self._close(events)

    async def _emit(self, send: Send, body: bytes) -> None:
        """Send one SSE event. A client that cannot keep up must not hold the session lock forever."""
        try:
            async with asyncio.timeout(self._send_timeout):
                await send({"type": "http.response.body", "body": body, "more_body": True})
        except TimeoutError:
            raise _ClientGone() from None  # stalled reader
        except Exception:
            raise _ClientGone() from None  # connection already closed

    async def _emit_error(self, send: Send, exc: Exception) -> None:
        """Tell the client why the stream ended. Only a safe code and message are sent, never provider details."""
        if isinstance(exc, AppError):
            code, message = exc.code, exc.message
        else:
            code, message = "internal_error", "Internal server error"
        await self._emit(send, format_sse("error", {"code": code, "message": message, "request_id": self._request_id}))

    @staticmethod
    async def _close(events: AsyncIterator[StreamEvent]) -> None:
        aclose = getattr(events, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                logger.debug("closing the event generator failed", exc_info=False)
