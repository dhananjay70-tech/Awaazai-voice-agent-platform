"""Provider-independent streaming text-to-speech interface.

The TTS service depends only on this, never on a vendor wire format. Kept separate from the Gemini text provider
(app/llm) and the speech-to-text provider (app/stt): they have different lifecycles and failure modes.
"""

from collections.abc import AsyncIterator
from typing import Protocol


class TTSProvider(Protocol):
    name: str
    content_type: str  # MIME type of every byte stream this provider returns, e.g. "audio/mpeg"

    def default_voice_for(self, language: str) -> str:
        """The voice used when the request names none. `language` is one of our names (english, hindi, hinglish)."""
        ...

    def stream(self, *, text: str, voice: str, language: str | None = None) -> AsyncIterator[bytes]:
        """Synthesize `text` (never translated or rewritten) and yield audio bytes as the provider produces them.

        Raises Tts*Error on failure. Closing the iterator (aclose) must release the upstream connection immediately.
        """
        ...
