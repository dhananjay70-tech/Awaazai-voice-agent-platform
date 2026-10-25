"""Service settings, loaded from environment variables (and an optional .env file).

Conventions mirror the Backend (pydantic-settings, validated at startup) but share no code with it:
the two services are deployed and versioned independently.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VOICEAGENT_DIR = Path(__file__).resolve().parents[1]
VOICE_PATTERN = re.compile(r"aura(-2)?-[a-z]+-[a-z]{2}")  # Deepgram TTS model ids, e.g. aura-2-thalia-en
SPEAKER_PATTERN = re.compile(r"[a-z][a-z0-9_]{1,63}")  # Sarvam speaker ids, e.g. shubh, simran_enhi_customer
LANGUAGE_CODE_PATTERN = re.compile(r"[a-z]{2,3}-[A-Z]{2}")  # BCP-47 as Sarvam writes it, e.g. hi-IN


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=VOICEAGENT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "awaazai-voiceagent"
    service_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # --- LLM provider (Phase 2) ---
    llm_provider: Literal["gemini"] = "gemini"
    # No default and never logged. The service starts without it; /chat then answers with a clear 503.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    llm_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    llm_temperature: float = Field(default=0.7, ge=0, le=2)
    llm_max_output_tokens: int = Field(default=512, ge=16, le=8192)

    # --- Streaming and concurrency (Phase 3A) ---
    # LLM_TIMEOUT_SECONDS (above) is also the longest wait for the NEXT chunk of a stream, and the longest a
    # stalled client may block a send. These add the whole-generation limit and the concurrency bounds.
    llm_stream_timeout_seconds: float = Field(default=60.0, gt=0, le=600)  # whole streamed generation
    llm_max_concurrent_generations: int = Field(default=8, ge=1, le=200)  # simultaneous Gemini calls (chat + stream)
    generation_queue_timeout_seconds: float = Field(default=5.0, gt=0, le=60)  # wait for a free slot before 503

    # --- Speech-to-text (Phase 3B): Deepgram live streaming ---
    stt_provider: Literal["deepgram"] = "deepgram"
    # No default and never logged. The service starts without it; /stt/stream then reports stt_not_configured.
    deepgram_api_key: SecretStr | None = None
    deepgram_model: str = "nova-3"
    # Must be wss:// (the key is sent in a header). ws:// is accepted only for localhost, so tests can use a local server.
    deepgram_url: str = "wss://api.deepgram.com/v1/listen"
    # Our language names -> Deepgram language codes. Hinglish has NO documented Deepgram mode: "multi" is Nova-3's
    # multilingual code-switching mode (it lists Hindi and English). Change these if it misbehaves on your audio.
    deepgram_language_english: str = "en"
    deepgram_language_hindi: str = "hi"
    deepgram_language_hinglish: str = "multi"
    deepgram_endpointing_ms: int = Field(default=300, ge=10, le=5000)  # silence that marks the end of an utterance
    # Deepgram's code-switching guide recommends endpointing=100 for `multi`, so Hinglish gets its own (editable) value.
    deepgram_endpointing_ms_hinglish: int = Field(default=100, ge=10, le=5000)
    stt_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    stt_idle_timeout_seconds: float = Field(default=8.0, gt=0, le=9)  # Deepgram closes after ~10 s without audio
    stt_finish_timeout_seconds: float = Field(default=10.0, gt=0, le=60)  # wait for final transcripts after "end"
    stt_send_timeout_seconds: float = Field(default=10.0, gt=0, le=60)  # a slow client may not hold a stream forever
    stt_max_stream_seconds: float = Field(default=300.0, gt=0, le=3600)  # wall-clock limit for one stream
    stt_max_audio_seconds: float = Field(default=120.0, gt=0, le=3600)  # total audio accepted per stream
    stt_max_chunk_bytes: int = Field(default=32_768, ge=320, le=262_144)  # one binary frame (1 s of 16 kHz mono PCM16)
    stt_max_concurrent_streams: int = Field(default=4, ge=1, le=100)
    # Browsers send an Origin header on WebSocket handshakes: only these may connect. Clients without an Origin
    # header (scripts, curl, the Backend) are not affected. Comma-separated.
    stt_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Text-to-speech (Phase 3C): Deepgram Aura or Sarvam Bulbul, both over streaming HTTP, always MP3 ---
    tts_provider: Literal["deepgram", "sarvam"] = "deepgram"
    # Deepgram reuses DEEPGRAM_API_KEY (above); MP3 is fixed at 22050 Hz. Aura has no Hindi voice.
    deepgram_tts_url: str = "https://api.deepgram.com/v1/speak"  # https:// only (http:// for localhost test servers)
    deepgram_tts_model: str = "aura-2-thalia-en"  # default voice; Deepgram documents NO Hindi voice model
    # Extra voices a client may request by name (comma-separated). Anything else is rejected, never passed through.
    deepgram_tts_voices: str = ""
    deepgram_tts_bit_rate: int = 48000  # 32000 or 48000 (checked below: env values are strings, so no int Literal)
    # Sarvam AI Bulbul (docs.sarvam.ai). No default and never logged; empty means "not configured".
    sarvam_api_key: SecretStr | None = None
    sarvam_tts_url: str = "https://api.sarvam.ai/text-to-speech/stream"  # https:// only (http:// for localhost tests)
    sarvam_tts_model: Literal["bulbul:v2", "bulbul:v3", "bulbul:v4-flash"] = "bulbul:v4-flash"  # Sarvam's recommended one
    # Our language names -> Sarvam BCP-47 codes. Sarvam does not say which code its code-mixed (`enhi`) voices expect:
    # hi-IN is the default for Hinglish; change it if listening tests say otherwise.
    sarvam_language_english: str = "en-IN"
    sarvam_language_hindi: str = "hi-IN"
    sarvam_language_hinglish: str = "hi-IN"
    # Default speaker per language. Speakers belong to ONE model: these are bulbul:v4-flash ids (`<name>_<lang>_<style>`;
    # `enhi` = English-Hindi code-mixed). For bulbul:v3 use plain names such as `shubh`; the two do not mix.
    sarvam_speaker_english: str = "dev_en_conversational"
    sarvam_speaker_hindi: str = "kavya_hi_conversational"
    sarvam_speaker_hinglish: str = "simran_enhi_customer"
    sarvam_tts_voices: str = ""  # extra speakers a client may request by name (comma-separated)
    sarvam_tts_sample_rate: int = 24000  # 8000, 16000, 22050 or 24000: streaming accepts nothing higher
    sarvam_tts_bitrate: Literal["32k", "64k", "96k", "128k", "192k"] = "128k"
    tts_timeout_seconds: float = Field(default=15.0, gt=0, le=120)  # connect, and the wait for each next audio chunk
    tts_stream_timeout_seconds: float = Field(default=60.0, gt=0, le=600)  # whole synthesis
    tts_send_timeout_seconds: float = Field(default=10.0, gt=0, le=60)  # a stalled client may not hold a slot forever
    tts_max_text_chars: int = Field(default=2000, ge=1, le=2000)  # 2000 is Deepgram's own per-request limit
    tts_max_concurrent_requests: int = Field(default=4, ge=1, le=100)
    tts_queue_timeout_seconds: float = Field(default=2.0, ge=0, le=60)  # wait for a free slot before 503

    # --- Voice turns (Phase 4, step 1): WS /voice/stream = text or audio in -> Gemini -> sentence-by-sentence speech ---
    # STT, Gemini and TTS keep their own limits above; these bound the whole pipeline. WebSocket sends reuse
    # STT_SEND_TIMEOUT_SECONDS, waiting for a client message reuses STT_IDLE_TIMEOUT_SECONDS, and browser origins
    # reuse STT_ALLOWED_ORIGINS.
    voice_max_concurrent_turns: int = Field(default=4, ge=1, le=100)
    # From the moment the user's text is known (typed, or transcribed) until the last audio is sent. Listening to the
    # user is bounded separately by the STT_* limits.
    voice_turn_timeout_seconds: float = Field(default=90.0, gt=0, le=900)
    voice_sentence_queue_size: int = Field(default=3, ge=1, le=16)  # finished sentences waiting for TTS; full = Gemini waits
    voice_max_sentence_chars: int = Field(default=300, ge=20, le=2000)  # longest piece sent to TTS in one request

    # --- In-memory conversation sessions (lost on restart, not shared between workers) ---
    session_max_sessions: int = Field(default=1000, ge=1, le=100_000)  # LRU-evicted beyond this
    session_ttl_seconds: float = Field(default=1800, gt=0)  # idle sessions expire
    session_max_turns: int = Field(default=20, ge=1, le=200)  # one turn = user message + assistant reply
    session_max_history_chars: int = Field(default=12_000, ge=500, le=500_000)
    session_lock_timeout_seconds: float = Field(default=30.0, gt=0, le=300)  # wait for a busy session

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def blank_key_means_missing(cls, value):
        # `GEMINI_API_KEY=` (empty) in .env must behave like "not configured", not like a real key.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("deepgram_api_key", "sarvam_api_key", mode="before")
    @classmethod
    def blank_deepgram_key_means_missing(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _validate_stt(self) -> "Settings":
        parsed = urlparse(self.deepgram_url)
        if parsed.scheme == "ws":
            if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError("DEEPGRAM_URL must use wss:// (ws:// is only allowed for localhost)")
        elif parsed.scheme != "wss":
            raise ValueError("DEEPGRAM_URL must be a wss:// URL")
        if self.environment == "production" and "*" in self.stt_origin_list:
            raise ValueError("STT_ALLOWED_ORIGINS must not contain '*' when ENVIRONMENT=production")
        return self

    @model_validator(mode="after")
    def _validate_tts(self) -> "Settings":
        parsed = urlparse(self.deepgram_tts_url)
        if parsed.scheme == "http":
            if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError("DEEPGRAM_TTS_URL must use https:// (http:// is only allowed for localhost)")
        elif parsed.scheme != "https":
            raise ValueError("DEEPGRAM_TTS_URL must be an https:// URL")
        for voice in (self.deepgram_tts_model, *_split_csv(self.deepgram_tts_voices)):
            if not VOICE_PATTERN.fullmatch(voice):
                raise ValueError("DEEPGRAM_TTS voices must look like 'aura-2-thalia-en' (lowercase model-voice-language)")
        if self.deepgram_tts_bit_rate not in (32000, 48000):
            raise ValueError("DEEPGRAM_TTS_BIT_RATE must be 32000 or 48000")
        if self.sarvam_tts_sample_rate not in (8000, 16000, 22050, 24000):
            raise ValueError("SARVAM_TTS_SAMPLE_RATE must be 8000, 16000, 22050 or 24000 (streaming limit)")
        parsed = urlparse(self.sarvam_tts_url)
        if parsed.scheme == "http":
            if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError("SARVAM_TTS_URL must use https:// (http:// is only allowed for localhost)")
        elif parsed.scheme != "https":
            raise ValueError("SARVAM_TTS_URL must be an https:// URL")
        for speaker in (*self.sarvam_default_speakers.values(), *_split_csv(self.sarvam_tts_voices)):
            if not SPEAKER_PATTERN.fullmatch(speaker):
                raise ValueError("Sarvam speakers must be lowercase ids such as 'shubh' or 'simran_enhi_customer'")
        for code in self.sarvam_language_codes.values():
            if not LANGUAGE_CODE_PATTERN.fullmatch(code):
                raise ValueError("SARVAM_LANGUAGE_* must be BCP-47 codes such as 'hi-IN'")
        return self

    @property
    def sarvam_language_codes(self) -> dict[str, str]:
        return {"english": self.sarvam_language_english, "hindi": self.sarvam_language_hindi, "hinglish": self.sarvam_language_hinglish}

    @property
    def sarvam_default_speakers(self) -> dict[str, str]:
        return {"english": self.sarvam_speaker_english, "hindi": self.sarvam_speaker_hindi, "hinglish": self.sarvam_speaker_hinglish}

    @property
    def tts_voice_list(self) -> list[str]:
        return _split_csv(self.sarvam_tts_voices if self.tts_provider == "sarvam" else self.deepgram_tts_voices)

    @property
    def tts_allowed_voices(self) -> frozenset[str]:
        """Voices a client may name in a request, for the configured TTS provider. Nothing else is passed through."""
        if self.tts_provider == "sarvam":
            return frozenset([*self.sarvam_default_speakers.values(), *self.tts_voice_list])
        return frozenset([self.deepgram_tts_model, *self.tts_voice_list])

    @property
    def stt_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.stt_allowed_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
