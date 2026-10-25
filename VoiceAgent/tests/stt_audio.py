"""Test-audio helpers for the opt-in real-STT smoke test.

`read_wav_pcm16` loads a WAV file as raw 16-bit mono PCM (what /stt/stream expects). `synthesize_speech` makes a short
spoken sentence with Windows' built-in speech synthesizer (System.Speech), so the smoke test can run without anyone
recording audio. Both are only used by opt-in tests: nothing here runs in the normal suite.
"""

import subprocess
import sys
import tempfile
import wave
from pathlib import Path


def read_wav_pcm16(path: str | Path) -> tuple[bytes, int]:
    """Return (PCM bytes, sample_rate) for a mono 16-bit WAV, or raise ValueError with a clear reason."""
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError(f"need mono 16-bit PCM WAV, got channels={wav.getnchannels()} sample_width={wav.getsampwidth()}")
        return wav.readframes(wav.getnframes()), wav.getframerate()


_SCRIPT = """
param([string]$Text, [string]$Out, [int]$Rate)
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo($Rate, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$synth.SetOutputToWaveFile($Out, $format)
$synth.Speak($Text)
$synth.Dispose()
"""


def synthesize_speech(text: str, sample_rate: int = 16000) -> tuple[bytes, int] | None:
    """Speak `text` with Windows SAPI and return (PCM bytes, sample_rate), or None if that is not available here."""
    if sys.platform != "win32":
        return None
    with tempfile.TemporaryDirectory() as folder:
        script, wav_path = Path(folder) / "speak.ps1", Path(folder) / "speech.wav"
        script.write_text(_SCRIPT, encoding="utf-8")
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                 "-Text", text, "-Out", str(wav_path), "-Rate", str(sample_rate)],
                check=True, capture_output=True, timeout=60,
            )
            return read_wav_pcm16(wav_path)
        except (subprocess.SubprocessError, OSError, ValueError, wave.Error):
            return None
