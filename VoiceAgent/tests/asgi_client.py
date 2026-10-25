"""A tiny in-process ASGI client that sees a response message by message.

Starlette's TestClient and httpx's ASGITransport both buffer the whole response, so they cannot show whether
tokens are delivered progressively or whether the server reacts to a client that disconnects or stalls.
This harness drives the real app (including its middleware) through the raw ASGI interface instead.
"""

import asyncio
import json

TIMEOUT = 3.0  # every wait is bounded: a regression must fail fast, never hang the suite


def parse_sse(raw: bytes) -> list[tuple[str, dict]]:
    events = []
    for block in raw.decode("utf-8").split("\n\n"):
        if not block.strip():
            continue
        name, data = None, None
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        events.append((name, data))
    return events


class Call:
    """One HTTP request in flight against `app`."""

    def __init__(self, app, body: dict, path: str = "/chat/stream", stall_after_bodies: int | None = None):
        self._incoming: asyncio.Queue = asyncio.Queue()
        self._outgoing: asyncio.Queue = asyncio.Queue()
        self._stall_after = stall_after_bodies
        self._bodies_sent = 0
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self._buffer = b""
        self._complete = False
        payload = json.dumps(body).encode()
        self._incoming.put_nowait({"type": "http.request", "body": payload, "more_body": False})
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
            "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
            "headers": [(b"host", b"test"), (b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())],
            "client": ("127.0.0.1", 50000), "server": ("test", 80), "state": {},
        }
        self.task = asyncio.create_task(app(scope, self._receive, self._send))

    async def _receive(self):
        return await self._incoming.get()

    async def _send(self, message):
        if message["type"] == "http.response.body" and self._stall_after is not None:
            if self._bodies_sent >= self._stall_after:
                await asyncio.Event().wait()  # a client that stopped reading: backpressure forever
            self._bodies_sent += 1
        await self._outgoing.put(message)

    def disconnect(self) -> None:
        self._incoming.put_nowait({"type": "http.disconnect"})

    async def _next_message(self):
        return await asyncio.wait_for(self._outgoing.get(), TIMEOUT)

    async def read_start(self) -> int:
        message = await self._next_message()
        assert message["type"] == "http.response.start", message
        self.status = message["status"]
        self.headers = {k.decode().lower(): v.decode() for k, v in message["headers"]}
        return self.status

    async def next_event(self) -> tuple[str, dict] | None:
        """The next complete SSE event, or None once the response has ended."""
        while True:
            if b"\n\n" in self._buffer:
                block, self._buffer = self._buffer.split(b"\n\n", 1)
                return parse_sse(block + b"\n\n")[0]
            if self._complete:
                return None
            message = await self._next_message()
            assert message["type"] == "http.response.body", message
            self._buffer += message.get("body", b"")
            if not message.get("more_body", False):
                self._complete = True

    async def events(self) -> list[tuple[str, dict]]:
        collected = []
        while (event := await self.next_event()) is not None:
            collected.append(event)
        return collected

    async def next_body(self) -> bytes | None:
        """The next raw body chunk (for binary streams), or None once the response has ended."""
        if self._complete:
            return None
        message = await self._next_message()
        assert message["type"] == "http.response.body", message
        if not message.get("more_body", False):
            self._complete = True
            return message.get("body", b"") or None
        return message["body"]

    async def json_body(self) -> dict:
        """For a non-streamed (error) response."""
        raw = b""
        while True:
            message = await self._next_message()
            raw += message.get("body", b"")
            if not message.get("more_body", False):
                return json.loads(raw)

    async def finished(self) -> None:
        await asyncio.wait_for(asyncio.shield(self.task), TIMEOUT)

    def no_message_pending(self) -> bool:
        return self._outgoing.empty()


async def wait_until(predicate, timeout: float = TIMEOUT) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition not reached in time"
        await asyncio.sleep(0.005)


class WsCall:
    """One WebSocket connection against `app`, driven through the raw ASGI interface (every wait is bounded)."""

    def __init__(self, app, headers: dict[str, str] | None = None, path: str = "/stt/stream", stall_after_sends: int | None = None):
        self._incoming: asyncio.Queue = asyncio.Queue()
        self._outgoing: asyncio.Queue = asyncio.Queue()
        self._stall_after = stall_after_sends
        self._sends = 0
        self.accepted = False
        self.accept_headers: dict[str, str] = {}
        self.close_code: int | None = None
        self.rejected = False
        self.closed = False
        raw_headers = [(b"host", b"test")] + [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
        scope = {
            "type": "websocket", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
            "scheme": "ws", "path": path, "raw_path": path.encode(), "query_string": b"", "headers": raw_headers,
            "client": ("127.0.0.1", 50001), "server": ("test", 80), "subprotocols": [], "state": {},
        }
        self._incoming.put_nowait({"type": "websocket.connect"})
        self.task = asyncio.create_task(app(scope, self._receive, self._send), name="ws-app")

    async def _receive(self):
        return await self._incoming.get()

    async def _send(self, message):
        if message["type"] == "websocket.send" and self._stall_after is not None:
            if self._sends >= self._stall_after:
                await asyncio.Event().wait()  # a client that stopped reading
            self._sends += 1
        await self._outgoing.put(message)

    # ---- client -> server
    def send_json(self, data) -> None:
        self._incoming.put_nowait({"type": "websocket.receive", "text": json.dumps(data)})

    def send_text(self, text: str) -> None:
        self._incoming.put_nowait({"type": "websocket.receive", "text": text})

    def send_bytes(self, data: bytes) -> None:
        self._incoming.put_nowait({"type": "websocket.receive", "bytes": data})

    def disconnect(self, code: int = 1000) -> None:
        self._incoming.put_nowait({"type": "websocket.disconnect", "code": code})

    # ---- server -> client
    async def _next(self):
        return await asyncio.wait_for(self._outgoing.get(), TIMEOUT)

    async def wait_accepted(self) -> bool:
        """True once the server accepted the handshake, False if it refused it (closed before accepting)."""
        message = await self._next()
        if message["type"] == "websocket.accept":
            self.accepted = True
            self.accept_headers = {k.decode().lower(): v.decode() for k, v in message.get("headers", [])}
            return True
        assert message["type"] == "websocket.close", message
        self.rejected, self.closed, self.close_code = True, True, message.get("code", 1000)
        return False

    async def next_event(self) -> dict | None:
        """The next JSON event from the server, or None when the server closed the connection."""
        if self.closed:
            return None
        message = await self._next()
        if message["type"] == "websocket.close":
            self.closed, self.close_code = True, message.get("code", 1000)
            return None
        assert message["type"] == "websocket.send", message
        return json.loads(message["text"])

    async def events(self) -> list[dict]:
        collected = []
        while (event := await self.next_event()) is not None:
            collected.append(event)
        return collected

    async def next_item(self) -> dict | bytes | None:
        """The next server message: a dict for a JSON text frame, bytes for a binary frame, None once closed."""
        if self.closed:
            return None
        message = await self._next()
        if message["type"] == "websocket.close":
            self.closed, self.close_code = True, message.get("code", 1000)
            return None
        assert message["type"] == "websocket.send", message
        if message.get("bytes") is not None:
            return message["bytes"]
        return json.loads(message["text"])

    async def items(self) -> list[dict | bytes]:
        collected = []
        while (item := await self.next_item()) is not None:
            collected.append(item)
        return collected

    def nothing_pending(self) -> bool:
        return self._outgoing.empty()

    async def finished(self) -> None:
        await asyncio.wait_for(asyncio.shield(self.task), TIMEOUT)
