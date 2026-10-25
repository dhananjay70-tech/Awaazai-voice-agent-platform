"""OPTIONAL real-provider TTS smoke test and voice-quality listening kit. It makes real (billable) calls: one short
request per phrase (English, Hindi, Hinglish) to whichever provider TTS_PROVIDER selects (deepgram or sarvam).

Skipped by default. It runs only when BOTH are true:
  1. the environment variable RUN_TTS_SMOKE=1 is set explicitly, and
  2. the API key of the selected provider is configured (DEEPGRAM_API_KEY or SARVAM_API_KEY, in the environment or .env).

It prints metadata only (status, content type, byte count, time to first audio chunk, total time, whether the bytes
look like MP3). It never prints keys, the phrases or the audio. Each phrase is saved so YOU can listen and judge:

    VoiceAgent/tts_samples/<provider>-<language>.mp3        (override the folder with TTS_SMOKE_DIR)

A passing test only proves that real MP3 audio came back. It says NOTHING about pronunciation quality: that is a
human judgement (see "Voice-quality listening plan" in the README).

    $env:TTS_PROVIDER = "sarvam"; $env:RUN_TTS_SMOKE = "1"; python -m pytest tests/test_tts_smoke.py -v -s
"""

import os
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from app.config import VOICEAGENT_DIR, Settings
from app.main import create_app

settings = Settings()  # real environment and VoiceAgent/.env (the only tests that read it, besides the other smoke tests)

PHRASES = {
    "english": "Hello! I can help you book an appointment and answer your questions.",
    "hindi": "नमस्ते! मैं आपकी मदद कर सकता हूँ। आप क्या जानना चाहते हैं?",
    "hinglish": "Namaste! Main aapki appointment book karne mein help kar sakta hoon.",
}

SELECTED_KEY = settings.sarvam_api_key if settings.tts_provider == "sarvam" else settings.deepgram_api_key

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_TTS_SMOKE") != "1" or SELECTED_KEY is None,
    reason="real TTS smoke test: set RUN_TTS_SMOKE=1 and configure the selected TTS_PROVIDER's API key to run",
)


@pytest.fixture
def live_server():
    app = create_app(Settings(environment="test", log_level="WARNING"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    port = server.servers[0].sockets[0].getsockname()[1]
    yield app, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


@pytest.mark.parametrize("language", list(PHRASES))
def test_real_provider_synthesizes_the_evaluation_phrase(live_server, language):
    app, base = live_server
    started = time.perf_counter()
    first_chunk_ms = None
    audio = b""
    with httpx.Client(timeout=60) as client:
        with client.stream("POST", f"{base}/tts/stream", json={"text": PHRASES[language], "language": language}) as response:
            status, content_type = response.status_code, response.headers.get("content-type")
            for chunk in response.iter_bytes():
                if first_chunk_ms is None:
                    first_chunk_ms = (time.perf_counter() - started) * 1000
                audio += chunk
    total_ms = (time.perf_counter() - started) * 1000
    looks_like_mp3 = audio[:3] == b"ID3" or (len(audio) > 1 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0)

    folder = Path(os.environ.get("TTS_SMOKE_DIR") or VOICEAGENT_DIR / "tts_samples")
    saved = ""
    if status == 200 and audio:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{settings.tts_provider}-{language}.mp3").write_bytes(audio)
        saved = f"saved={folder.name}/{settings.tts_provider}-{language}.mp3"
    print(f"\n[real tts] provider={settings.tts_provider} language={language} status={status} content_type={content_type} "
          f"audio_bytes={len(audio)} first_chunk_ms={first_chunk_ms and round(first_chunk_ms)} total_ms={round(total_ms)} "
          f"looks_like_mp3={looks_like_mp3} {saved}")
    assert status == 200 and content_type == "audio/mpeg"
    assert len(audio) > 1000, "suspiciously little audio"
    assert looks_like_mp3
    assert app.state.tts_service.limiter.in_use == 0, "a TTS slot was leaked"
