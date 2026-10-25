"""Does cancelling a stream really stop the UPSTREAM HTTP request, using the real google-genai SDK?

A fake Gemini streaming endpoint runs on localhost (no internet, no key). It emits Server-Sent Events slowly and
records whether it was cancelled (the client closed the connection) or ran to completion. The real SDK and the
real GeminiProvider talk to it, so this verifies actual connection teardown rather than a mock's flag.

Limitation: this proves our process closes the connection. What Google's servers then do with an abandoned
generation is outside what any client can observe.
"""

import asyncio
import json
import threading

import pytest
import uvicorn
from google import genai
from google.genai import types
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

from app.llm.base import ChatMessage
from app.llm.gemini import GeminiProvider
from app.main import create_app
from tests.asgi_client import Call, wait_until
from tests.conftest import make_settings


class FakeGeminiServer:
    """Streams `total` chunks, one every `interval` seconds, and records how each request ended."""

    def __init__(self, total: int = 200, interval: float = 0.05):
        self.total, self.interval = total, interval
        self.requests = 0
        self.chunks_written = 0
        self.completed = threading.Event()  # the stream ran to its natural end
        self.cancelled = threading.Event()  # the client went away first
        self.ended = threading.Event()  # either of the above

        async def handler(request):
            self.requests += 1
            return StreamingResponse(self._body(), media_type="text/event-stream")

        app = Starlette(routes=[Route("/{path:path}", handler, methods=["POST"])])
        self._server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical"))
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    async def _body(self):
        try:
            for i in range(self.total):
                payload = {"candidates": [{"content": {"role": "model", "parts": [{"text": f"chunk{i} "}]}}]}
                yield f"data: {json.dumps(payload)}\r\n\r\n".encode()
                self.chunks_written += 1
                await asyncio.sleep(self.interval)
            self.completed.set()
        except asyncio.CancelledError:
            self.cancelled.set()  # raised when the client's connection closes
            raise
        finally:
            self.ended.set()

    def __enter__(self):
        self._thread.start()
        deadline = threading.Event()
        for _ in range(100):
            if self._server.started:
                break
            deadline.wait(0.05)
        assert self._server.started, "fake Gemini server did not start"
        self.port = self._server.servers[0].sockets[0].getsockname()[1]
        return self

    def __exit__(self, *exc):
        self._server.should_exit = True
        self._thread.join(5)

    def provider(self) -> GeminiProvider:
        client = genai.Client(
            api_key="local-test-key-not-real",
            http_options=types.HttpOptions(base_url=f"http://127.0.0.1:{self.port}", timeout=5000),
        )
        return GeminiProvider(
            api_key="unused", model="local-model", timeout_seconds=5, temperature=0.5, max_output_tokens=64, client=client
        )


def messages():
    return [ChatMessage("user", "hi")]


async def wait_for_event(event: threading.Event, timeout: float = 5.0) -> bool:
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(loop.run_in_executor(None, event.wait, timeout), timeout + 1)


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 30))


# ---------------------------------------------------------------- control: detection is meaningful

def test_control_an_uninterrupted_stream_completes_and_is_not_seen_as_cancelled():
    with FakeGeminiServer(total=4, interval=0.02) as server:
        async def scenario():
            provider = server.provider()
            chunks = [c async for c in provider.stream(system_instruction="SYS", messages=messages())]
            await provider.aclose()
            return chunks

        chunks = run(scenario())
        assert "".join(chunks) == "chunk0 chunk1 chunk2 chunk3 "  # the real SDK parsed the real SSE stream
        assert server.completed.wait(3) and not server.cancelled.is_set()


# ---------------------------------------------------------------- the real thing

def test_closing_the_provider_stream_closes_the_upstream_connection():
    with FakeGeminiServer() as server:
        async def scenario():
            provider = server.provider()
            iterator = provider.stream(system_instruction="SYS", messages=messages())
            assert (await asyncio.wait_for(anext(iterator), 5)).startswith("chunk0")
            written_before = server.chunks_written
            await iterator.aclose()  # the consumer abandons the answer
            assert await wait_for_event(server.cancelled), "the upstream request was NOT cancelled"
            await asyncio.sleep(0.4)
            await provider.aclose()
            return written_before

        written_before = run(scenario())
        assert not server.completed.is_set()
        assert server.chunks_written <= written_before + 2, "the server kept generating for a client that was gone"
        assert server.chunks_written < 20


def test_cancelling_the_consuming_task_closes_the_upstream_connection():
    with FakeGeminiServer() as server:
        async def scenario():
            provider = server.provider()
            got_first = asyncio.Event()

            async def consume():
                async for _ in provider.stream(system_instruction="SYS", messages=messages()):
                    got_first.set()

            task = asyncio.create_task(consume())
            await asyncio.wait_for(got_first.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert await wait_for_event(server.cancelled), "the upstream request was NOT cancelled"
            await provider.aclose()

        run(scenario())
        assert not server.completed.is_set() and server.chunks_written < 20


def test_client_disconnect_on_chat_stream_cancels_the_upstream_gemini_request():
    """The whole chain: browser disconnects -> our server cancels -> SDK stream closed -> upstream connection closed."""
    with FakeGeminiServer() as server:
        async def scenario():
            app = create_app(make_settings(llm_timeout_seconds=5), llm_provider=server.provider())
            call = Call(app, {"message": "hi", "session_id": "s"})
            await call.read_start()
            assert (await call.next_event())[0] == "start"
            assert (await call.next_event())[0] == "token"
            await wait_until(lambda: server.chunks_written >= 1)

            call.disconnect()  # the browser tab closes
            await call.finished()
            assert await wait_for_event(server.cancelled), "disconnecting the client did NOT stop the Gemini request"
            session = app.state.chat_service._store._sessions["s"]
            assert not session.lock.locked() and app.state.chat_service.limiter.in_use == 0
            await app.state.chat_service.aclose()

        run(scenario())
        assert not server.completed.is_set()
        assert server.chunks_written < 20


def test_idle_timeout_cancels_the_upstream_request_too():
    with FakeGeminiServer(total=200, interval=2.0) as server:  # Gemini goes quiet for 2 s between chunks
        async def scenario():
            app = create_app(make_settings(llm_timeout_seconds=0.4), llm_provider=server.provider())
            call = Call(app, {"message": "hi", "session_id": "s"})
            await call.read_start()
            events = await call.events()
            await call.finished()
            assert [n for n, _ in events][-1] == "error" and events[-1][1]["code"] == "llm_timeout"
            assert await wait_for_event(server.cancelled), "the timed-out upstream request was left running"
            await app.state.chat_service.aclose()

        run(scenario())
