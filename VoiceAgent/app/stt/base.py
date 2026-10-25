"""Provider-independent streaming speech-to-text interface.

The stream service depends only on these types, never on a vendor SDK or wire format. Keep it separate from the
text-generation provider (app/llm): STT and LLM are different services with different credentials and lifecycles.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

AUDIO_ENCODING = "linear16"  # raw PCM, signed 16-bit little-endian: the only encoding this phase accepts
BYTES_PER_SAMPLE = 2
# Deepgram's linear16 needs an explicit sample_rate; these are the rates we accept (browsers resample to one of them).
ALLOWED_SAMPLE_RATES = (8000, 16000, 22050, 24000, 44100, 48000)


@dataclass(frozen=True)
class AudioFormat:
    encoding: str
    sample_rate: int
    channels: int

    @property
    def frame_bytes(self) -> int:
        """Bytes in one sample frame; every audio chunk must be a whole number of these."""
        return BYTES_PER_SAMPLE * self.channels

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.frame_bytes


@dataclass(frozen=True)
class TranscriptEvent:
    """One transcription result from the provider.

    kind="partial": a hypothesis for the speech currently being spoken. It may change and is superseded by later
    partials and finally by a "final". kind="final": stable text for one audio segment; finals never repeat earlier
    text, so concatenating them (in order) gives the transcript.
    """

    kind: Literal["partial", "final"]
    text: str
    start: float = 0.0  # seconds from the start of the stream
    duration: float = 0.0
    speech_final: bool = False  # the speaker paused: a good moment to treat the utterance as complete
    confidence: float | None = None


class STTSession(Protocol):
    """One live transcription session (one provider connection)."""

    async def send_audio(self, chunk: bytes) -> None:
        """Forward audio. Applies backpressure (awaits) instead of buffering without limit."""
        ...

    async def finish(self) -> None:
        """No more audio is coming: ask the provider to flush and end. The events() iterator then completes."""
        ...

    def events(self) -> AsyncIterator[TranscriptEvent]:
        """Transcript events until the provider ends the session. Raises Stt*Error on failure."""
        ...

    async def aclose(self) -> None:
        """Release the provider connection immediately. Idempotent; safe after errors and cancellation."""
        ...


class STTProvider(Protocol):
    name: str
    model: str

    async def open(self, *, language: str, audio: AudioFormat) -> STTSession:
        """Connect and start a session. `language` is one of our names (english, hindi, hinglish)."""
        ...
