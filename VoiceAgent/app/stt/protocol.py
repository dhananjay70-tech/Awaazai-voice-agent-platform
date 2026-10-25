"""The client-facing protocol of WS /stt/stream: the config message and the server events.

Client -> server:
  1. one TEXT frame, first:   {"type":"config","encoding":"linear16","sample_rate":16000,"channels":1,"language":"hinglish"}
  2. BINARY frames:           raw PCM (signed 16-bit little-endian, mono), a whole number of samples per frame
  3. one TEXT frame, last:    {"type":"end"}                      (or just close the connection to cancel)

Server -> client (TEXT frames, JSON, always with a "type"):
  ready    {"type","stream_id","request_id","language","model","sample_rate","channels"}
  partial  {"type","seq","text"}                                  interim hypothesis, only sent when it changed
  final    {"type","seq","text","start","duration","speech_final","confidence"}   stable text for one segment
  done     {"type","stream_id","audio_seconds","partials","finals","first_partial_ms","first_final_ms","total_ms"}
  error    {"type","code","message","request_id","details"?}      then the server closes the connection
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.prompts import Language
from app.stt.base import ALLOWED_SAMPLE_RATES, AUDIO_ENCODING

MAX_CONTROL_MESSAGE_BYTES = 4096  # config / end messages are tiny; anything bigger is not one of them


class SttConfigMessage(BaseModel):
    # extra="forbid": unknown fields are rejected, never silently ignored. strict=True: no type coercion, so
    # {"sample_rate": "16000"} (a string) or {"channels": true} are errors, not silently "fixed".
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["config"]
    encoding: Literal["linear16"] = AUDIO_ENCODING
    sample_rate: int
    channels: int = 1
    language: Language = "hinglish"

    @field_validator("sample_rate")
    @classmethod
    def supported_rate(cls, value: int) -> int:
        if value not in ALLOWED_SAMPLE_RATES:
            raise ValueError(f"sample_rate must be one of {list(ALLOWED_SAMPLE_RATES)}")
        return value

    @field_validator("channels")
    @classmethod
    def mono_only(cls, value: int) -> int:
        if value != 1:
            raise ValueError("only mono audio (channels=1) is supported")
        return value


def ready_event(*, stream_id: str, request_id: str, language: str, model: str, sample_rate: int, channels: int) -> dict[str, Any]:
    return {
        "type": "ready", "stream_id": stream_id, "request_id": request_id, "language": language,
        "model": model, "sample_rate": sample_rate, "channels": channels,
    }


def partial_event(seq: int, text: str) -> dict[str, Any]:
    return {"type": "partial", "seq": seq, "text": text}


def final_event(seq: int, text: str, start: float, duration: float, speech_final: bool, confidence: float | None) -> dict[str, Any]:
    return {
        "type": "final", "seq": seq, "text": text, "start": start, "duration": duration,
        "speech_final": speech_final, "confidence": confidence,
    }


def done_event(**fields: Any) -> dict[str, Any]:
    return {"type": "done", **fields}


def error_event(code: str, message: str, request_id: str, details: Any = None) -> dict[str, Any]:
    event: dict[str, Any] = {"type": "error", "code": code, "message": message, "request_id": request_id}
    if details is not None:
        event["details"] = details
    return event
