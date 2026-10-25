"""Deepgram Aura text-to-speech over its streaming HTTP endpoint: POST https://api.deepgram.com/v1/speak.

Protocol facts, taken from Deepgram's current docs (not from memory):
- Auth: `Authorization: Token <API_KEY>` header. Body: JSON {"text": "..."}, at most 2000 characters (else HTTP 413).
- Query parameters used: model (e.g. aura-2-thalia-en), encoding=mp3, bit_rate (32000 or 48000). MP3 is fixed at
  22050 Hz and answered as `audio/mpeg`.
- The response body is the audio, streamed as it is generated. Errors are plain HTTP statuses.
- Voices: Aura-2 documents English, Spanish, German, French, Dutch, Italian and Japanese. NO Hindi model exists, so
  `language` does not change anything here: use the Sarvam provider for Hindi and Hinglish.

We use `httpx` (already installed and pinned) rather than the Deepgram SDK. The API key only ever appears in the
request header.
"""

from collections.abc import AsyncIterator

import httpx

from app.tts.http import stream_audio

CONTENT_TYPE = "audio/mpeg"


class DeepgramTtsProvider:
    name = "deepgram"
    content_type = CONTENT_TYPE

    def __init__(
        self,
        *,
        api_key: str,
        default_voice: str,
        url: str,
        bit_rate: int,
        timeout_seconds: float,
        max_connections: int = 10,
    ) -> None:
        self.default_voice = default_voice
        self._api_key = api_key
        self._url = url
        self._bit_rate = bit_rate
        # `timeout_seconds` bounds connecting and each wait for the next bytes; the service bounds the whole synthesis.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(max_connections=max_connections),
        )

    def default_voice_for(self, language: str) -> str:
        return self.default_voice  # one voice for every language: Aura has no Hindi model

    async def aclose(self) -> None:
        await self._client.aclose()

    def stream(self, *, text: str, voice: str, language: str | None = None) -> AsyncIterator[bytes]:
        return stream_audio(
            self._client,
            self._url,
            provider="Deepgram",
            params={"model": voice, "encoding": "mp3", "bit_rate": self._bit_rate},
            json_body={"text": text},
            headers={"Authorization": f"Token {self._api_key}", "Accept": CONTENT_TYPE},
        )
