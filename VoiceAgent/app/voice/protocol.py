"""The client-facing protocol of WS /voice/stream, and the voice-specific errors.

One connection carries one voice turn: the user's words go in, Gemini's reply comes back as text AND speech.

Client -> server:
  1. one TEXT frame, first:  {"type":"config","language":"hinglish","session_id":"optional","sample_rate":16000}
        language: english | hindi | hinglish (default hinglish); session_id: reuse a chat session (random if omitted);
        sample_rate: required only when sending audio (raw mono PCM16, same rules as WS /stt/stream)
  2. then EITHER one TEXT frame:        {"type":"text","text":"Namaste, kaise ho?"}
     OR binary frames (raw mono PCM16, no WAV header) followed by a TEXT frame {"type":"end"}
  Closing the connection at any time cancels the turn.

Server -> client (JSON TEXT frames with a "type", plus BINARY frames of MP3 audio):
  ready        {"type","request_id","session_id","language","sample_rate"}
  partial      {"type","seq","text"}          audio input only: same events as WS /stt/stream
  final        {"type","seq","text","start","duration","speech_final","confidence"}
  reply_text   {"type","text"}                a piece of Gemini's reply, as soon as it exists (concatenate them)
  audio_start  {"type","index","content_type"}     a spoken sentence begins; the BINARY frames that follow belong to it
  <binary>                                    MP3 bytes of sentence `index` (always the most recent audio_start)
  audio_end    {"type","index","complete","bytes"}  complete=false if speech for this sentence failed part-way
  error        {"type","stage","code","message","request_id","fatal","details"?}
  done         {"type","request_id","session_id","model","language","audio_complete","sentences","audio_bytes",
                "first_text_ms","first_audio_ms","transcript_ms","total_ms"}

Terminal events: a turn ends with exactly ONE of `done` (success) or an `error` with fatal=true (failure); the
connection then closes. A `tts` error with fatal=false is a warning inside a turn that still ends with `done` and
audio_complete=false: the reply text was delivered and the conversation history stored, only the speech was lost.
`stage` is one of: stt, llm, tts, protocol, server.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.errors import AppError
from app.prompts import Language
from app.schemas import MAX_MESSAGE_CHARS, SESSION_ID_PATTERN
from app.stt.base import ALLOWED_SAMPLE_RATES, AUDIO_ENCODING

MAX_CONTROL_MESSAGE_BYTES = 4 * MAX_MESSAGE_CHARS + 512  # a text message may hold MAX_MESSAGE_CHARS non-ASCII characters


# ---------------------------------------------------------------- errors (all safe to show to the client)

class VoiceError(AppError):
    close_code = 1011  # WebSocket close code used after the error event
    stage = "protocol"  # which stage of the turn the error is reported for


class VoiceIdleTimeoutError(VoiceError):
    status_code = 408
    code = "voice_idle_timeout"
    message = "No message was received for too long."
    close_code = 1008


class VoiceInvalidConfigError(VoiceError):
    status_code = 422
    code = "voice_invalid_config"
    message = "The voice stream configuration is invalid."
    close_code = 1008


class VoiceInvalidMessageError(VoiceError):
    status_code = 422
    code = "voice_invalid_message"
    message = "Unsupported message. Send text, or binary audio frames followed by {\"type\":\"end\"}."
    close_code = 1008


class VoiceNoSpeechError(VoiceError):
    status_code = 422
    code = "voice_no_speech"
    message = "No speech was recognized in the audio."
    close_code = 1000
    stage = "stt"


class VoiceTranscriptTooLongError(VoiceError):
    status_code = 413
    code = "voice_transcript_too_long"
    message = "The recognized speech is too long to send to the assistant."
    close_code = 1009
    stage = "stt"


class VoiceCapacityError(VoiceError):
    status_code = 503
    code = "voice_capacity_reached"
    message = "Too many voice conversations are active right now. Please retry shortly."
    close_code = 1013
    stage = "server"


class VoiceTurnTimeoutError(VoiceError):
    status_code = 504
    code = "voice_turn_timeout"
    message = "The voice turn took too long and was stopped."
    close_code = 1011
    stage = "server"


# ---------------------------------------------------------------- client messages

class VoiceConfigMessage(BaseModel):
    # strict=True and extra="forbid": same rules as the STT config message (no silent coercion, no unknown fields).
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["config"]
    language: Language = "hinglish"
    session_id: str | None = Field(default=None, pattern=SESSION_ID_PATTERN)
    encoding: Literal["linear16"] = AUDIO_ENCODING
    sample_rate: int | None = None
    channels: int = 1
    voice: str | None = None

    @field_validator("sample_rate")
    @classmethod
    def supported_rate(cls, value: int | None) -> int | None:
        if value is not None and value not in ALLOWED_SAMPLE_RATES:
            raise ValueError(f"sample_rate must be one of {list(ALLOWED_SAMPLE_RATES)}")
        return value

    @field_validator("channels")
    @classmethod
    def mono_only(cls, value: int) -> int:
        if value != 1:
            raise ValueError("only mono audio (channels=1) is supported")
        return value


class VoiceSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = Field(default=None, pattern=SESSION_ID_PATTERN)
    agent_id: str | None = None
    system_prompt: str | None = Field(default=None, max_length=10_000)
    language: Language | None = None
    voice: str | None = Field(default=None, max_length=100)


class VoiceSessionResponse(BaseModel):
    session_id: str
    agent_id: str | None = None
    language: str
    voice: str | None = None


class VoiceTextMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["text"]
    text: str = Field(max_length=MAX_MESSAGE_CHARS)

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Text must contain non-whitespace characters")
        return value


# ---------------------------------------------------------------- server events

def ready_event(*, request_id: str, session_id: str, language: str, sample_rate: int | None) -> dict[str, Any]:
    return {"type": "ready", "request_id": request_id, "session_id": session_id, "language": language, "sample_rate": sample_rate}


def reply_text_event(text: str) -> dict[str, Any]:
    return {"type": "reply_text", "text": text}


def audio_start_event(index: int, content_type: str) -> dict[str, Any]:
    return {"type": "audio_start", "index": index, "content_type": content_type}


def audio_end_event(index: int, complete: bool, size: int) -> dict[str, Any]:
    return {"type": "audio_end", "index": index, "complete": complete, "bytes": size}


def error_event(stage: str, exc: AppError, request_id: str, *, fatal: bool) -> dict[str, Any]:
    """Only the exception's safe code and message are ever sent, never provider text or exception details."""
    event: dict[str, Any] = {
        "type": "error", "stage": stage, "code": exc.code, "message": exc.message, "request_id": request_id, "fatal": fatal,
    }
    if exc.details is not None:
        event["details"] = exc.details
    return event


def done_event(**fields: Any) -> dict[str, Any]:
    return {"type": "done", **fields}
