"""OPTIONAL real-Deepgram STT smoke test. It makes real (billable) calls and streams a few seconds of audio.

Skipped by default. It runs only when BOTH are true:
  1. the environment variable RUN_STT_SMOKE=1 is set explicitly, and
  2. DEEPGRAM_API_KEY is configured (in the environment or VoiceAgent/.env).

Audio: by default an English sentence is synthesized with Windows' built-in speech (System.Speech), so nobody has to record
anything. Provide your own with STT_SMOKE_AUDIO=<path to a mono 16-bit PCM WAV>. To evaluate Hinglish on YOUR audio,
record short WAVs and set STT_SMOKE_HINDI_AUDIO, STT_SMOKE_HINGLISH_AUDIO (romanised Hinglish) and/or
STT_SMOKE_MIXED_AUDIO (Devanagari Hindi with English words): the evaluation cases at the bottom report only counts of
Devanagari and Latin letters in the transcript, never the text itself. Cases without a WAV are skipped.

It never prints or asserts on the key, or on transcript text beyond a keyword check reported as a boolean.

    $env:RUN_STT_SMOKE = "1"; python -m pytest tests/test_stt_smoke.py -v -s
"""

import asyncio
import json
import os
import threading
import time

import pytest
import uvicorn
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.config import Settings
from app.main import create_app
from tests.stt_audio import read_wav_pcm16, synthesize_speech

settings = Settings()  # real environment and VoiceAgent/.env (the only tests that read it, besides the other smoke tests)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_STT_SMOKE") != "1" or settings.deepgram_api_key is None,
    reason="real-Deepgram smoke test: set RUN_STT_SMOKE=1 and configure DEEPGRAM_API_KEY to run",
)

FRAME_SECONDS = 0.02  # stream in 20 ms frames, paced like a live microphone


@pytest.fixture
def live_server():
    app = create_app(Settings(environment="test", log_level="WARNING"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical", ws="websockets-sansio"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    port = server.servers[0].sockets[0].getsockname()[1]
    yield app, f"ws://127.0.0.1:{port}/stt/stream"
    server.should_exit = True
    thread.join(5)


async def transcribe(url: str, pcm: bytes, sample_rate: int, language: str) -> list[dict]:
    frame_bytes = int(sample_rate * FRAME_SECONDS) * 2
    events: list[dict] = []
    async with connect(url, max_size=2**20) as ws:
        await ws.send(json.dumps({"type": "config", "encoding": "linear16", "sample_rate": sample_rate, "channels": 1, "language": language}))

        async def receive():
            try:
                async for message in ws:
                    events.append(json.loads(message))
            except ConnectionClosed:
                pass

        reader = asyncio.create_task(receive())
        for offset in range(0, len(pcm), frame_bytes):
            await ws.send(pcm[offset:offset + frame_bytes])
            await asyncio.sleep(FRAME_SECONDS)  # real-time pacing
        await ws.send(b"\x00\x00" * int(sample_rate * 0.6))  # a little trailing silence lets the last words finalize
        await ws.send(json.dumps({"type": "end"}))
        await asyncio.wait_for(reader, 30)
    return events


def test_real_deepgram_transcribes_english_speech_incrementally(live_server):
    app, url = live_server
    audio_path = os.environ.get("STT_SMOKE_AUDIO")
    if audio_path:
        pcm, rate = read_wav_pcm16(audio_path)
    else:
        synthesized = synthesize_speech("Hello, this is a test of speech recognition.")
        if synthesized is None:
            pytest.skip("no audio: set STT_SMOKE_AUDIO to a mono 16-bit WAV (Windows speech synthesis is unavailable)")
        pcm, rate = synthesized

    events = asyncio.run(asyncio.wait_for(transcribe(url, pcm, rate, "english"), 90))
    types = [e["type"] for e in events]
    errors = [e["code"] for e in events if e["type"] == "error"]
    assert not errors, f"stream failed with {errors}"
    assert types[0] == "ready" and types[-1] == "done", f"unexpected event sequence: {types[:2]}...{types[-2:]}"
    finals = [e for e in events if e["type"] == "final"]
    assert finals and all(f["text"].strip() for f in finals), "no final transcript was produced"
    done = events[-1]
    assert done["finals"] == len(finals) and done["first_final_ms"] > 0

    transcript = " ".join(f["text"] for f in finals).lower()
    keyword_found = any(word in transcript for word in ("test", "speech", "recognition", "hello"))
    print(f"\n[real stt] audio_seconds={len(pcm) / (rate * 2):.1f} partials={done['partials']} finals={done['finals']} "
          f"first_partial_ms={done['first_partial_ms']} first_final_ms={done['first_final_ms']} keyword_found={keyword_found}")
    assert keyword_found, "the transcript contains none of the spoken keywords"
    assert app.state.stt_service.limiter.in_use == 0, "a stream slot was leaked"


# Real-speech evaluation cases: (id, audio env var, language mode sent to /stt/stream). Each needs a mono 16-bit PCM WAV
# that YOU recorded (Windows speech synthesis has no Hindi voice). Cases without a WAV are skipped, never faked.
# Suggested short, natural phrases (see the README, "Evaluating Hindi and Hinglish STT"):
#   english                 "Hello, I would like to book an appointment for tomorrow."                  (STT_SMOKE_AUDIO, above)
#   hindi (Devanagari)      "नमस्ते, मैं कल अपॉइंटमेंट बुक करना चाहता हूँ।"                                 (STT_SMOKE_HINDI_AUDIO)
#   romanised Hinglish      "Main kal appointment book karna chahta hoon, please confirm kar dena."      (STT_SMOKE_HINGLISH_AUDIO)
#   Devanagari + English    "मुझे कल का appointment confirm करना है।" (spoken with the English words)      (STT_SMOKE_MIXED_AUDIO)
EVALUATION_CASES = [
    ("hindi-mode-hindi-audio", "STT_SMOKE_HINDI_AUDIO", "hindi"),
    ("multi-mode-hindi-audio", "STT_SMOKE_HINDI_AUDIO", "hinglish"),
    ("multi-mode-romanised-hinglish", "STT_SMOKE_HINGLISH_AUDIO", "hinglish"),
    ("hindi-mode-romanised-hinglish", "STT_SMOKE_HINGLISH_AUDIO", "hindi"),
    ("multi-mode-devanagari-with-english", "STT_SMOKE_MIXED_AUDIO", "hinglish"),
]


@pytest.mark.parametrize("case, env_var, language", EVALUATION_CASES, ids=[c[0] for c in EVALUATION_CASES])
def test_real_deepgram_language_evaluation_reports_script_counts_only(live_server, case, env_var, language):
    if not os.environ.get(env_var):
        pytest.skip(f"set {env_var}=<mono 16-bit WAV path> to run this evaluation case")
    app, url = live_server
    pcm, rate = read_wav_pcm16(os.environ[env_var])
    events = asyncio.run(asyncio.wait_for(transcribe(url, pcm, rate, language), 120))
    assert not [e for e in events if e["type"] == "error"], "stream failed"
    finals = [e["text"] for e in events if e["type"] == "final"]
    text = " ".join(finals)
    devanagari = sum(1 for ch in text if "ऀ" <= ch <= "ॿ")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    done = events[-1]
    # Numbers only, never the transcript: which script Hindi words come back in is exactly what this measures.
    print(f"\n[real stt] case={case} mode={language} audio_seconds={len(pcm) / (rate * 2):.1f} final_segments={len(finals)} "
          f"devanagari_letters={devanagari} latin_letters={latin} first_final_ms={done.get('first_final_ms')}")
    assert devanagari + latin > 0, "empty transcript"
    assert app.state.stt_service.limiter.in_use == 0, "a stream slot was leaked"
