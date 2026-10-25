"""Phase 3D: English, Hindi and Hinglish STT modes: provider parameters, endpointing, and script-preserving transcripts.

Offline only. These tests prove OUR side: the right Deepgram parameters are sent per language, and whatever text comes
back (Devanagari, Roman or mixed) reaches the client unchanged. They say nothing about how well real Deepgram
recognises real Hindi or Hinglish speech: only the opt-in smoke tests (tests/test_stt_smoke.py) can.
"""

import asyncio
import unicodedata

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import build_stt_provider, create_app
from app.stt.base import AudioFormat
from tests.asgi_client import WsCall
from tests.conftest import make_settings
from tests.fake_deepgram import FakeDeepgramServer, results
from tests.stt_fakes import FakeSTTProvider, final, partial

AUDIO = AudioFormat("linear16", 16000, 1)
CHUNK = b"\x01\x00" * 160
KEY = "fake-deepgram-key-NOT-A-REAL-KEY-0123456789"

DEVANAGARI = "नमस्ते, मैं आपकी मदद कर सकता हूँ।"
ROMAN_HINGLISH = "Main kal office jaunga, please meeting book kar dena."
MIXED = "मुझे कल का appointment confirm करना है।"
TEXTS = {"english": "Please book a table for two.", "hindi": DEVANAGARI, "hinglish": ROMAN_HINGLISH}


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


# ---------------------------------------------------------------- what is sent to Deepgram, per language

@pytest.mark.parametrize(
    "language, code, endpointing",
    [("english", "en", "300"), ("hindi", "hi", "300"), ("hinglish", "multi", "100")],
)
def test_each_mode_opens_nova3_with_its_documented_language_and_endpointing(language, code, endpointing):
    with FakeDeepgramServer() as server:
        async def scenario():
            provider = build_stt_provider(make_settings(deepgram_api_key=KEY, deepgram_url=server.url))
            session = await provider.open(language=language, audio=AUDIO)
            await session.aclose()

        run(scenario())
    query = server.handshakes[0]["query"]
    assert query["model"] == "nova-3" and query["language"] == code and query["endpointing"] == endpointing
    assert query["encoding"] == "linear16" and query["interim_results"] == "true"
    assert server.handshakes[0]["authorization"] == f"Token {KEY}"


def test_hinglish_endpointing_and_language_code_are_configurable():
    with FakeDeepgramServer() as server:
        async def scenario():
            settings = make_settings(
                deepgram_api_key=KEY, deepgram_url=server.url, deepgram_endpointing_ms=500,
                deepgram_endpointing_ms_hinglish=250, deepgram_language_english="en-IN", deepgram_language_hinglish="hi",
            )
            provider = build_stt_provider(settings)
            for language in ("english", "hindi", "hinglish"):
                await (await provider.open(language=language, audio=AUDIO)).aclose()

        run(scenario())
    seen = [(h["query"]["language"], h["query"]["endpointing"]) for h in server.handshakes]
    assert seen == [("en-IN", "500"), ("hi", "500"), ("hi", "250")]


def test_endpointing_settings_parse_from_environment_strings_and_are_validated(monkeypatch):
    monkeypatch.delenv("DEEPGRAM_ENDPOINTING_MS_HINGLISH", raising=False)
    assert make_settings().deepgram_endpointing_ms_hinglish == 100 and make_settings().deepgram_endpointing_ms == 300
    for bad in (5, 6000):
        with pytest.raises(ValidationError):
            make_settings(deepgram_endpointing_ms_hinglish=bad)
    monkeypatch.setenv("DEEPGRAM_ENDPOINTING_MS_HINGLISH", "150")
    assert Settings(_env_file=None).deepgram_endpointing_ms_hinglish == 150


# ---------------------------------------------------------------- transcripts are never translated or rewritten

@pytest.mark.parametrize("text", [DEVANAGARI, ROMAN_HINGLISH, MIXED, "Hello, this is English."])
def test_provider_returns_partial_and_final_text_unchanged_in_any_script(text):
    script = {1: [results(text[:6], start=0.0)], 2: [results(text, is_final=True, speech_final=True, duration=1.0)]}
    with FakeDeepgramServer(on_audio=script) as server:
        async def scenario():
            provider = build_stt_provider(make_settings(deepgram_api_key=KEY, deepgram_url=server.url))
            session = await provider.open(language="hinglish", audio=AUDIO)
            await session.send_audio(CHUNK)
            await session.send_audio(CHUNK)
            await session.finish()
            events = [e async for e in session.events()]
            await session.aclose()
            return events

        events = run(scenario())
    assert [e.kind for e in events] == ["partial", "final"]
    assert events[1].text == text and unicodedata.normalize("NFC", events[1].text) == unicodedata.normalize("NFC", text)
    assert events[1].text.encode("utf-8") == text.encode("utf-8")  # byte-identical: no normalisation, no transliteration


@pytest.mark.parametrize("language", ["english", "hindi", "hinglish"])
def test_websocket_protocol_is_unchanged_for_every_mode(language):
    text = TEXTS[language]
    provider = FakeSTTProvider(
        on_chunk={1: [partial(text[:5])], 2: [final(text, speech_final=True)]},
        on_finish=[final(MIXED, start=1.0)],
    )

    async def scenario():
        app = create_app(make_settings(), stt_provider=provider)
        call = WsCall(app)
        assert await call.wait_accepted()
        call.send_json({"type": "config", "encoding": "linear16", "sample_rate": 16000, "channels": 1, "language": language})
        ready = await call.next_event()
        call.send_bytes(CHUNK)
        call.send_bytes(CHUNK)
        call.send_json({"type": "end"})
        events = [ready] + await call.events()
        await call.finished()
        return events

    events = run(scenario())
    assert [e["type"] for e in events] == ["ready", "partial", "final", "final", "done"]
    assert events[0]["language"] == language and provider.opened[0][0] == language
    assert events[2]["text"] == text and events[3]["text"] == MIXED  # Devanagari, Roman and mixed text pass through intact
    assert set(events[2]) == {"type", "seq", "text", "start", "duration", "speech_final", "confidence"}  # same fields as before


def test_existing_clients_without_a_language_still_get_hinglish():
    provider = FakeSTTProvider(on_finish=[final(ROMAN_HINGLISH)])

    async def scenario():
        call = WsCall(create_app(make_settings(), stt_provider=provider))
        assert await call.wait_accepted()
        call.send_json({"type": "config", "sample_rate": 16000})  # the Phase 3B minimum
        ready = await call.next_event()
        call.send_json({"type": "end"})
        return ready, await call.events()

    ready, events = run(scenario())
    assert ready["language"] == "hinglish" and events[0]["text"] == ROMAN_HINGLISH


def test_unsupported_language_is_still_rejected():
    async def scenario():
        call = WsCall(create_app(make_settings(), stt_provider=FakeSTTProvider()))
        assert await call.wait_accepted()
        call.send_json({"type": "config", "sample_rate": 16000, "language": "hi-Latn"})  # not a documented Nova-3 mode
        return await call.events()

    events = run(scenario())
    assert events[-1]["type"] == "error" and events[-1]["code"] == "stt_invalid_config"
