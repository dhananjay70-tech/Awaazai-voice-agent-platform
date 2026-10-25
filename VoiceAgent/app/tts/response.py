"""The streamed audio response for POST /tts/stream.

Same ownership rule as EventStreamResponse (app/streaming.py): the audio generator, which holds the concurrency slot
and the upstream HTTP connection, is only started inside __call__, in a task that is always cancelled and awaited in
a `finally`. A failure before the first audio chunk is therefore a normal JSON error with a real HTTP status. A
failure AFTER the response started cannot change the status: the connection is aborted (the exception propagates, the
terminating chunk is never sent) so the client sees a truncated download instead of audio that looks complete.
"""

import asyncio
import logging
from collections.abc import AsyncIterator

from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from app.errors import AppError

logger = logging.getLogger(__name__)

DISCONNECTED_BEFORE_START = 499  # nginx convention: "client closed request"


class AudioStreamInterrupted(Exception):
    """The audio stream failed after the response had started. Carries only a safe error code."""


class _ClientGone(Exception):
    pass


class AudioStreamResponse(Response):
    def __init__(self, chunks: AsyncIterator[bytes], *, media_type: str, send_timeout_seconds: float) -> None:
        super().__init__(content=None, status_code=200, media_type=media_type)
        self._chunks = chunks
        self._send_timeout = send_timeout_seconds
        self._response_started = False
        self.raw_headers = [
            (b"content-type", media_type.encode()),
            (b"cache-control", b"no-store, no-transform"),
            (b"x-accel-buffering", b"no"),  # tells nginx-style proxies not to buffer the audio
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        pump = asyncio.create_task(self._pump(send), name="tts-pump")
        watcher = asyncio.create_task(self._watch_disconnect(receive), name="tts-disconnect-watcher")
        try:
            await asyncio.wait({pump, watcher}, return_when=asyncio.FIRST_COMPLETED)
            if pump.done():
                pump.result()  # before the start: propagates to the JSON handlers; after it: AudioStreamInterrupted
            else:
                await self._cancel(pump)  # the client left: stop synthesizing and release everything
                if not self._response_started:
                    await send({"type": "http.response.start", "status": DISCONNECTED_BEFORE_START, "headers": []})
                    await send({"type": "http.response.body", "body": b""})
        finally:
            await self._cancel(pump, watcher)

    @staticmethod
    async def _cancel(*tasks: asyncio.Task) -> None:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)  # waits for the pump's `finally` to release everything

    @staticmethod
    async def _watch_disconnect(receive: Receive) -> None:
        while True:
            if (await receive())["type"] == "http.disconnect":
                return

    async def _pump(self, send: Send) -> None:
        chunks = self._chunks
        try:
            first = await anext(chunks)  # may raise: nothing is sent yet, so the caller still gets a real HTTP error
            await send({"type": "http.response.start", "status": 200, "headers": self.raw_headers})
            self._response_started = True
            try:
                await self._emit(send, first)
                while True:
                    try:
                        chunk = await anext(chunks)
                    except StopAsyncIteration:
                        break
                    except Exception as exc:  # synthesis failed after the audio started
                        code = exc.code if isinstance(exc, AppError) else "internal_error"
                        raise AudioStreamInterrupted(code) from None
                    await self._emit(send, chunk)
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            except _ClientGone:
                logger.debug("TTS client stopped reading; stream closed")
        finally:
            aclose = getattr(chunks, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    logger.debug("closing the audio generator failed", exc_info=False)

    async def _emit(self, send: Send, body: bytes) -> None:
        try:
            async with asyncio.timeout(self._send_timeout):
                await send({"type": "http.response.body", "body": body, "more_body": True})
        except Exception:  # stalled reader (timeout) or connection already closed
            raise _ClientGone() from None
