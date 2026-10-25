"""Provider-independent LLM interface. Routes and services depend on this, never on a vendor SDK."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    text: str


class LLMProvider(Protocol):
    model: str

    async def generate(self, *, system_instruction: str, messages: Sequence[ChatMessage]) -> str:
        """Return the assistant's reply to the conversation.

        `system_instruction` is trusted, server-written text and is passed separately from `messages`
        (which contain user-supplied text). Implementations must raise the LLM*Error types from
        app.errors for every failure and must never return an empty or fabricated reply.
        """
        ...

    def stream(self, *, system_instruction: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        """Yield the reply as text chunks, as soon as the provider produces them (an async generator).

        Same contract as generate(): failures raise the LLM*Error types and an empty reply raises
        LLMBadResponseError. Closing the iterator (aclose) or cancelling the consuming task must stop the
        upstream request, so no generation keeps running for a client that is gone.
        """
        ...

    async def aclose(self) -> None:
        """Release network resources."""
        ...
