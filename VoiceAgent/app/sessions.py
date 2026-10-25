"""Bounded in-memory conversation sessions.

Limits (all configurable, see app.config):
- at most `max_sessions` sessions; the least recently used idle one is evicted to make room
- idle sessions expire after `ttl_seconds`
- each session keeps at most `max_turns` turns and `max_history_chars` characters (oldest turns dropped first)

Concurrency: every session has its own asyncio.Lock that is held for the whole request (including the model
call). Two requests for the SAME session therefore run one after the other, so history cannot interleave or be
corrupted and the second request sees the first one's reply. Different sessions never block each other.

Limitations (by design for Phase 2): nothing is written to disk or a database, so sessions are lost on restart
and are NOT shared between worker processes. Run a single worker until a shared store is justified.
"""

import asyncio
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from app.errors import SessionBusyError, SessionLimitError
from app.llm.base import ChatMessage


class Session:
    def __init__(self, now: float, max_turns: int, max_history_chars: int) -> None:
        self.lock = asyncio.Lock()
        self.last_used = now
        self._max_messages = max_turns * 2  # a turn is a user message plus the assistant reply
        self._max_chars = max_history_chars
        self._history: list[ChatMessage] = []
        self.system_prompt: str | None = None
        self.language: str | None = None
        self.voice: str | None = None
        self.agent_id: str | None = None

    def messages(self) -> list[ChatMessage]:
        return list(self._history)  # a copy: callers cannot mutate stored history

    def append_turn(self, user_text: str, assistant_text: str) -> None:
        """Record a completed turn, then drop the oldest turns until the limits hold."""
        self._history.append(ChatMessage("user", user_text))
        self._history.append(ChatMessage("assistant", assistant_text))
        while len(self._history) > 2 and (
            len(self._history) > self._max_messages or self.total_chars > self._max_chars
        ):
            del self._history[:2]

    @property
    def total_chars(self) -> int:
        return sum(len(m.text) for m in self._history)


class SessionStore:
    def __init__(
        self,
        *,
        max_sessions: int,
        ttl_seconds: float,
        max_turns: int,
        max_history_chars: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_sessions = max_sessions
        self._ttl = ttl_seconds
        self._max_turns = max_turns
        self._max_chars = max_history_chars
        self._clock = clock
        self._sessions: OrderedDict[str, Session] = OrderedDict()  # least recently used first

    def __len__(self) -> int:
        return len(self._sessions)

    def get(self, session_id: str) -> Session | None:
        """Lookup an existing session without creating one."""
        now = self._clock()
        self._purge_expired(now)
        return self._sessions.get(session_id)

    def bind_session(
        self,
        session_id: str,
        *,
        system_prompt: str | None = None,
        language: str | None = None,
        voice: str | None = None,
        agent_id: str | None = None,
    ) -> Session:
        """Bind or pre-configure an agent session with custom instructions and voice settings."""
        session = self._get_or_create(session_id)
        if system_prompt is not None:
            session.system_prompt = system_prompt
        if language is not None:
            session.language = language
        if voice is not None:
            session.voice = voice
        if agent_id is not None:
            session.agent_id = agent_id
        return session

    @asynccontextmanager
    async def locked(self, session_id: str, lock_timeout_seconds: float) -> AsyncIterator[Session]:
        """Get (or create) the session and hold its lock for the duration of the `async with` block."""
        for _ in range(3):  # retry only in the rare case the session was evicted while we waited for its lock
            session = self._get_or_create(session_id)
            try:
                await asyncio.wait_for(session.lock.acquire(), timeout=lock_timeout_seconds)
            except TimeoutError:
                raise SessionBusyError() from None
            if self._sessions.get(session_id) is session:
                break
            session.lock.release()
        else:
            raise SessionBusyError()
        try:
            yield session
        finally:
            session.last_used = self._clock()
            session.lock.release()

    # ------------------------------------------------------------------ internals

    def _get_or_create(self, session_id: str) -> Session:
        now = self._clock()
        self._purge_expired(now)
        session = self._sessions.get(session_id)
        if session is None:
            if len(self._sessions) >= self._max_sessions:
                self._evict_least_recently_used()
            session = Session(now, self._max_turns, self._max_chars)
            self._sessions[session_id] = session
        session.last_used = now
        self._sessions.move_to_end(session_id)
        return session

    def _purge_expired(self, now: float) -> None:
        for sid in list(self._sessions):  # ordered oldest-use first
            session = self._sessions[sid]
            if now - session.last_used <= self._ttl:
                break  # everything after this was used even more recently
            if not session.lock.locked():
                del self._sessions[sid]

    def _evict_least_recently_used(self) -> None:
        for sid, session in self._sessions.items():
            if not session.lock.locked():  # never evict a conversation that is mid-request
                del self._sessions[sid]
                return
        raise SessionLimitError()
