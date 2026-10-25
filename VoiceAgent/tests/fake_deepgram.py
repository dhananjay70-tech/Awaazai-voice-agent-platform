"""A local fake of Deepgram's live streaming WebSocket (localhost only: no internet, no key).

It speaks the protocol from Deepgram's official AsyncAPI spec over REAL sockets, so the real DeepgramProvider and the
real `websockets` library are exercised end to end. It records what the client actually sent (handshake path/query,
Authorization header, audio frames, control messages) and how the connection ended.

This proves OUR client follows the documented protocol. It does not prove Deepgram's real service behaves as
documented, nor anything about real speech recognition quality.
"""

import asyncio
import json
import threading
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse

from websockets.asyncio.server import serve


def results(text: str, *, is_final: bool = False, speech_final: bool = False, start: float = 0.0,
            duration: float = 0.5, confidence: float | None = 0.99) -> dict:
    """A Deepgram `Results` message (shape per the official spec)."""
    alternative = {"transcript": text, "words": []}
    if confidence is not None:
        alternative["confidence"] = confidence
    return {
        "type": "Results", "channel_index": [0, 1], "duration": duration, "start": start,
        "is_final": is_final, "speech_final": speech_final, "from_finalize": False,
        "channel": {"alternatives": [alternative]},
        "metadata": {"request_id": "fake-request", "model_info": {"name": "fake"}},
    }


class FakeDeepgramServer:
    def __init__(self, *, reject_status: int | None = None, on_audio: dict | None = None, on_finalize: list | None = None,
                 on_close_stream: list | None = None, close_after_audio: tuple[int, int] | None = None,
                 hang_on_close_stream: bool = False):
        self.reject_status = reject_status
        self.on_audio = on_audio or {}  # n-th audio frame (1-based) -> list of messages (dict, str or bytes) to send
        self.on_finalize = on_finalize or []
        self.on_close_stream = on_close_stream or []
        self.close_after_audio = close_after_audio  # (n, close code): the server closes after the n-th frame
        self.hang_on_close_stream = hang_on_close_stream
        # what the client did
        self.handshakes: list[dict] = []
        self.audio_frames: list[bytes] = []
        self.control_messages: list[dict] = []
        self.client_gone = threading.Event()  # the client's connection ended
        self.client_close_code: int | None = None
        self.connections = 0
        self._started = threading.Event()
        self._stop: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.port = 0
        self._thread = threading.Thread(target=lambda: asyncio.run(self._main()), daemon=True)

    # ------------------------------------------------------------ lifecycle
    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/v1/listen"

    def __enter__(self):
        self._thread.start()
        assert self._started.wait(5), "fake Deepgram did not start"
        return self

    def __exit__(self, *exc):
        if self._loop and self._stop:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(5)

    async def _main(self):
        self._loop, self._stop = asyncio.get_running_loop(), asyncio.Event()

        def process_request(connection, request):
            parsed = urlparse(request.path)
            self.handshakes.append({
                "path": parsed.path,
                "query": {k: v[0] for k, v in parse_qs(parsed.query).items()},
                "authorization": request.headers.get("Authorization"),
            })
            if self.reject_status is not None:
                return connection.respond(HTTPStatus(self.reject_status), "rejected\n")
            return None

        async with serve(self._handler, "127.0.0.1", 0, process_request=process_request) as server:
            self.port = server.sockets[0].getsockname()[1]
            self._started.set()
            await self._stop.wait()

    # ------------------------------------------------------------ protocol
    @staticmethod
    async def _send_all(connection, messages):
        for message in messages:
            await connection.send(json.dumps(message) if isinstance(message, dict) else message)

    async def _handler(self, connection):
        self.connections += 1
        try:
            async for message in connection:
                if isinstance(message, bytes):
                    self.audio_frames.append(message)
                    n = len(self.audio_frames)
                    await self._send_all(connection, self.on_audio.get(n, []))
                    if self.close_after_audio and self.close_after_audio[0] == n:
                        await connection.close(self.close_after_audio[1])
                        return
                    continue
                control = json.loads(message)
                self.control_messages.append(control)
                if control.get("type") == "Finalize":
                    await self._send_all(connection, self.on_finalize)
                elif control.get("type") == "CloseStream":
                    await self._send_all(connection, self.on_close_stream)
                    if self.hang_on_close_stream:
                        await asyncio.Event().wait()
                    await connection.close(1000)
                    return
        except Exception:
            pass
        finally:
            self.client_close_code = connection.close_code
            self.client_gone.set()
