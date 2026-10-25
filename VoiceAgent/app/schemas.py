from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.prompts import Language

MAX_MESSAGE_CHARS = 2000
MAX_TTS_CHARS = 2000  # Deepgram's per-request TTS limit
SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class ChatRequest(BaseModel):
    # extra="forbid": unknown fields (e.g. a client-supplied user_id or permissions) are rejected, not ignored.
    model_config = ConfigDict(extra="forbid")

    message: str = Field(max_length=MAX_MESSAGE_CHARS)
    session_id: str | None = Field(default=None, pattern=SESSION_ID_PATTERN)  # generated when omitted
    language: Language = "hinglish"

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message must contain non-whitespace text")
        return value


class TtsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=MAX_TTS_CHARS)  # the configured TTS_MAX_TEXT_CHARS may be lower: checked in the service
    language: Language = "hinglish"
    # None or "default" selects the configured provider's default voice for `language`; any other value must be one
    # of the configured voices (DEEPGRAM_TTS_VOICES / SARVAM_TTS_VOICES and the default speakers).
    voice: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Text must contain non-whitespace characters")
        return value


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    model: str
