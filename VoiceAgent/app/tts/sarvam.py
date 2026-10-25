"""Sarvam AI Bulbul text-to-speech over its HTTP streaming endpoint: POST https://api.sarvam.ai/text-to-speech/stream.

Protocol facts, taken from Sarvam's current official docs (docs.sarvam.ai), not from memory:
- Auth: `api-subscription-key: <API_KEY>` header. Body: JSON. The response is raw audio bytes (not JSON) in the
  requested codec, e.g. `audio/mpeg` for mp3. Errors are JSON with status 400/403/422/429/500 (bodies are never read).
- Body fields used: text (required), model, language_code (BCP-47, e.g. hi-IN, en-IN), speaker (lowercase,
  case-sensitive, must belong to the chosen model), output_audio_codec=mp3, speech_sample_rate (8000-24000 when
  streaming), output_audio_bitrate.
- Models: bulbul:v4-flash is the one Sarvam recommends for new integrations; bulbul:v3 and bulbul:v2 also exist.
  v3/v4-flash always normalise English words and numbers, so `enable_preprocessing` is not sent.
- bulbul:v4-flash voices are named `<name>_<lang>_<style>`; `hi` = Hindi, `en` = English (en-IN), `enhi` =
  English-Hindi code-mixed (Hinglish). Sarvam does not say which `language_code` an `enhi` voice expects: it is
  configurable (SARVAM_LANGUAGE_HINGLISH) and must be checked by listening.
- Sarvam states that romanised Indic input "significantly reduces output quality" and recommends native script for
  Indic words. The text is therefore sent exactly as received: this service never transliterates or rewrites it.

`language` selects both the `language_code` and the default speaker. The API key only ever appears in the request header.
"""

from collections.abc import AsyncIterator

import httpx

from app.tts.http import stream_audio

CONTENT_TYPE = "audio/mpeg"


class SarvamTtsProvider:
    name = "sarvam"
    content_type = CONTENT_TYPE

    def __init__(
        self,
        *,
        api_key: str,
        url: str,
        model: str,
        language_codes: dict[str, str],  # english / hindi / hinglish -> BCP-47 code
        default_speakers: dict[str, str],  # english / hindi / hinglish -> speaker id
        sample_rate: int,
        bitrate: str,
        timeout_seconds: float,
        max_connections: int = 10,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._url = url
        self._language_codes = language_codes
        self._default_speakers = default_speakers
        self._sample_rate = sample_rate
        self._bitrate = bitrate
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(max_connections=max_connections),
        )

    def default_voice_for(self, language: str) -> str:
        return self._default_speakers[language]

    async def aclose(self) -> None:
        await self._client.aclose()

    def stream(self, *, text: str, voice: str, language: str | None = None) -> AsyncIterator[bytes]:
        return stream_audio(
            self._client,
            self._url,
            provider="Sarvam",
            params=None,
            json_body={
                "text": text,
                "model": self.model,
                "language_code": self._language_codes[language or "english"],
                "speaker": voice,
                "output_audio_codec": "mp3",
                "speech_sample_rate": self._sample_rate,
                "output_audio_bitrate": self._bitrate,
            },
            headers={"api-subscription-key": self._api_key, "Accept": CONTENT_TYPE},
        )
