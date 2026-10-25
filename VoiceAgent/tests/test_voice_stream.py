"""WS /voice/stream: text/audio in -> Gemini -> sentence-by-sentence speech, with fake STT, LLM and TTS providers.

Everything is offline and every wait is bounded, so a regression fails fast instead of hanging the suite.
"""

import asyncio
import logging

import pytest

from app.errors import LLMAuthError, TtsAuthError, TtsUnavailableError
from app.main import create_app
from tests.asgi_client import WsCall, wait_until
from tests.conftest import FakeProvider, make_settings
from tests.stt_fakes import FakeSTTProvider, final, partial
from tests.tts_fakes import FakeTTSProvider

CHUNK = b"\x01\x00" * 160  # 10 ms of 16 kHz mono 16-bit PCM = 320 bytes
CONFIG = {"type": "config", "language": "hinglish"}
REPLY = ["Namaste! ", "Main AwaazAI hoon. ", "Kaise help karoon?"]  # three sentences
SECRET_TEXT = "TOP-SECRET-USER-SENTENCE-12345"
SECRET_REPLY = "TOP-SECRET-REPLY-SENTENCE-67890."
SECRET_KEY = "voice-secret-key-do-not-leak"


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


def make_app(llm="default", stt="default", tts="default", **settings):
    llm = FakeProvider(chunks=REPLY) if llm == "default" else llm
    stt = FakeSTTProvider() if stt == "default" else stt
    tts = FakeTTSProvider([b"AAA", b"BBB"]) if tts == "default" else tts
    return create_app(make_settings(**settings), llm_provider=llm, stt_provider=stt, tts_provider=tts)


async def connect(app, config=CONFIG, headers=None, **call_kwargs) -> WsCall:
    call = WsCall(app, headers=headers, path="/voice/stream", **call_kwargs)
    assert await call.wait_accepted()
    if config is not None:
        call.send_json(config)
    return call


async def text_turn(app, text="Namaste", config=CONFIG) -> list:
    call = await connect(app, config)
    call.send_json({"type": "text", "text": text})
    items = await call.items()
    await call.finished()
    call.items_close_code = call.close_code
    return items


def events(items, kind=None):
    found = [i for i in items if isinstance(i, dict)]
    return [e for e in found if kind is None or e["type"] == kind]


def terminal_events(items):
    return [e for e in events(items) if e["type"] == "done" or (e["type"] == "error" and e["fatal"])]


def types(items):
    return [("audio" if isinstance(i, bytes) else i["type"]) for i in items]


async def assert_clean(app, *providers):
    """Nothing may be left behind: no slot in any limiter, nothing running upstream, no stray task."""
    await wait_until(lambda: all(
        limiter.in_use == 0 for limiter in (
            app.state.voice_service.limiter, app.state.chat_service.limiter,
            app.state.tts_service.limiter, app.state.stt_service.limiter,
        )
    ) and all(p.in_flight == 0 for p in providers if hasattr(p, "in_flight")))
    await asyncio.sleep(0.05)
    current = asyncio.current_task()
    stray = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    assert not stray, f"leaked tasks: {[t.get_name() for t in stray]}"


# ---------------------------------------------------------------- text turn: the happy path

def test_text_turn_streams_reply_text_and_one_audio_segment_per_sentence():
    llm, tts = FakeProvider(chunks=REPLY), FakeTTSProvider([b"AAA", b"BBB"])

    async def scenario():
        app = make_app(llm, tts=tts)
        call = await connect(app, {"type": "config", "language": "hinglish", "session_id": "voice-demo-1"})
        call.send_json({"type": "text", "text": "  Hello  "})
        items = await call.items()
        await call.finished()
        assert call.close_code == 1000

        kinds = types(items)
        assert kinds[0] == "ready" and kinds[-1] == "done"
        assert [kinds.count(k) for k in ("reply_text", "audio_start", "audio", "audio_end")] == [3, 3, 6, 3]
        # per sentence the order is audio_start, its binary frames, audio_end (reply_text events may interleave)
        audio_only = [k for k in kinds if k in ("audio_start", "audio", "audio_end")]
        assert audio_only == ["audio_start", "audio", "audio", "audio_end"] * 3
        ready, done = events(items, "ready")[0], events(items, "done")[0]
        assert ready["session_id"] == "voice-demo-1" and ready["language"] == "hinglish" and ready["sample_rate"] is None
        assert len(ready["request_id"]) == 16 and call.accept_headers["x-request-id"] == ready["request_id"]
        assert call.accept_headers["x-content-type-options"] == "nosniff" and call.accept_headers["cache-control"] == "no-store"

        assert "".join(e["text"] for e in events(items, "reply_text")) == "".join(REPLY).strip()
        starts, ends = events(items, "audio_start"), events(items, "audio_end")
        assert [s["index"] for s in starts] == [0, 1, 2] and all(s["content_type"] == "audio/mpeg" for s in starts)
        assert [(e["index"], e["complete"], e["bytes"]) for e in ends] == [(0, True, 6), (1, True, 6), (2, True, 6)]
        # every binary frame sits between its audio_start and audio_end, in order
        audio_blocks = []
        for item in items:
            if isinstance(item, dict) and item["type"] == "audio_start":
                audio_blocks.append(b"")
            elif isinstance(item, bytes):
                audio_blocks[-1] += item
        assert audio_blocks == [b"AAABBB"] * 3

        assert tts.calls == [("Namaste!", "aura-2-thalia-en"), ("Main AwaazAI hoon.", "aura-2-thalia-en"), ("Kaise help karoon?", "aura-2-thalia-en")]
        assert tts.languages == ["hinglish"] * 3
        assert llm.calls[0][1][-1].text == "Hello"  # the user's text, trimmed, reached Gemini
        assert (done["audio_complete"], done["sentences"], done["audio_bytes"], done["model"]) == (True, 3, 18, "fake-model")
        assert done["session_id"] == "voice-demo-1" and done["transcript_ms"] is None
        assert done["first_text_ms"] is not None and done["first_audio_ms"] >= done["first_text_ms"]
        assert len(terminal_events(items)) == 1
        await assert_clean(app, llm, tts)

    run(scenario())


@pytest.mark.parametrize("language", ["english", "hindi", "hinglish"])
def test_every_language_reaches_gemini_and_tts(language):
    llm, tts = FakeProvider(chunks=["Ek sentence. "]), FakeTTSProvider([b"A"])

    async def scenario():
        app = make_app(llm, tts=tts)
        items = await text_turn(app, "Hi", {"type": "config", "language": language})
        assert events(items, "ready")[0]["language"] == language and events(items, "done")[0]["language"] == language
        assert tts.languages == [language]
        assert f"{language}" in llm.calls[0][0].lower() or "Language preference" in llm.calls[0][0]

    run(scenario())


def test_history_is_stored_after_a_successful_turn_and_reused_by_the_next():
    llm = FakeProvider(chunks=["Pehla jawab. "])

    async def scenario():
        app = make_app(llm)
        config = {"type": "config", "session_id": "memory-1"}
        await text_turn(app, "pehla sawal", config)
        await text_turn(app, "doosra sawal", config)
        history = [(m.role, m.text) for m in llm.calls[1][1]]
        assert history == [("user", "pehla sawal"), ("assistant", "Pehla jawab."), ("user", "doosra sawal")]

    run(scenario())


def test_the_first_sentence_is_spoken_before_gemini_has_finished():
    gates = [asyncio.Event(), asyncio.Event()]
    llm = FakeProvider(chunks=["Pehla vaakya. ", "Doosra vaakya."], chunk_gates=gates)
    tts = FakeTTSProvider([b"AAA"])

    async def scenario():
        app = make_app(llm, tts=tts)
        call = await connect(app)
        call.send_json({"type": "text", "text": "hi"})
        gates[0].set()
        seen = []
        while not (seen and isinstance(seen[-1], dict) and seen[-1]["type"] == "audio_end"):
            seen.append(await call.next_item())
        assert [e["text"] for e in events(seen, "reply_text")] == ["Pehla vaakya. "]
        assert tts.calls == [("Pehla vaakya.", "aura-2-thalia-en")]
        assert llm.chunks_sent == 1 and not events(seen, "done")  # Gemini still has a chunk to produce
        gates[1].set()
        rest = await call.items()
        assert events(rest, "done")[0]["sentences"] == 2 and len(tts.calls) == 2
        await assert_clean(app, llm, tts)

    run(scenario())


def test_sentence_queue_is_bounded_so_gemini_waits_for_slow_speech():
    gate = asyncio.Event()
    llm = FakeProvider(chunks=[f"Vaakya number {i}. " for i in range(20)])
    tts = FakeTTSProvider([b"A"], chunk_gates=[gate])  # every synthesis waits until the gate opens

    async def scenario():
        app = make_app(llm, tts=tts, voice_sentence_queue_size=1)
        call = await connect(app)
        call.send_json({"type": "text", "text": "hi"})
        await wait_until(lambda: tts.started == 1)
        await asyncio.sleep(0.2)  # give Gemini every chance to race ahead
        assert llm.chunks_sent <= 4, f"Gemini ran ahead of speech: {llm.chunks_sent} of 20 chunks produced"
        assert app.state.voice_service.limiter.in_use == 1
        gate.set()
        items = await call.items()
        assert events(items, "done")[0]["sentences"] == 20 and len(tts.calls) == 20
        assert "".join(e["text"] for e in events(items, "reply_text")) == "".join(f"Vaakya number {i}. " for i in range(20))
        await assert_clean(app, llm, tts)

    run(scenario())


# ---------------------------------------------------------------- speech failures never lose the reply or the history

def test_speech_failing_on_the_second_sentence_keeps_the_text_flowing_and_ends_with_one_done():
    class FailsSecond(FakeTTSProvider):
        async def stream(self, *, text, voice, language=None):
            if len(self.calls) == 1:  # the second call
                self.calls.append((text, voice))
                raise TtsUnavailableError()
            async for chunk in super().stream(text=text, voice=voice, language=language):
                yield chunk

    llm, tts = FakeProvider(chunks=REPLY), FailsSecond([b"AAA"])

    async def scenario():
        app = make_app(llm, tts=tts)
        config = {"type": "config", "session_id": "tts-fail-1"}
        items = await text_turn(app, "hi", config)
        errors = events(items, "error")
        assert len(errors) == 1 and errors[0]["stage"] == "tts" and errors[0]["code"] == "tts_unavailable"
        assert errors[0]["fatal"] is False and len(errors[0]["request_id"]) == 16
        assert [e["index"] for e in events(items, "audio_end")] == [0]  # the first sentence was spoken completely
        assert len(tts.calls) == 2, "no more sentences are sent to TTS after it failed"
        assert "".join(e["text"] for e in events(items, "reply_text")) == "".join(REPLY).strip()  # the whole reply text
        done = events(items, "done")[0]
        assert done["audio_complete"] is False and done["sentences"] == 3
        assert len(terminal_events(items)) == 1 and items.index(errors[0]) < items.index(done)

        await text_turn(app, "again", config)  # the failed-speech turn was still stored in the conversation
        assert [(m.role, m.text) for m in llm.calls[1][1]][:2] == [("user", "hi"), ("assistant", "".join(REPLY).strip())]
        await assert_clean(app, llm, tts)

    run(scenario())


def test_speech_failing_part_way_through_a_sentence_closes_that_segment_as_incomplete():
    llm, tts = FakeProvider(chunks=["Ek vaakya. "]), FakeTTSProvider([b"AAA", b"BBB"], error=TtsUnavailableError(), error_after=1)

    async def scenario():
        app = make_app(llm, tts=tts)
        items = await text_turn(app)
        assert types(items) == ["ready", "reply_text", "audio_start", "audio", "audio_end", "error", "done"]
        assert events(items, "audio_end")[0] == {"type": "audio_end", "index": 0, "complete": False, "bytes": 3}
        assert events(items, "error")[0]["fatal"] is False and events(items, "done")[0]["audio_complete"] is False
        await assert_clean(app, llm, tts)

    run(scenario())


def test_speech_auth_failure_on_the_first_sentence_still_delivers_the_text():
    llm, tts = FakeProvider(chunks=REPLY), FakeTTSProvider(error=TtsAuthError())

    async def scenario():
        app = make_app(llm, tts=tts)
        items = await text_turn(app)
        assert events(items, "error")[0]["code"] == "tts_authentication_failed" and len(events(items, "error")) == 1
        assert not events(items, "audio_start") and tts.started == 1
        assert "".join(e["text"] for e in events(items, "reply_text")) == "".join(REPLY).strip()
        assert events(items, "done")[0]["audio_complete"] is False and len(terminal_events(items)) == 1

    run(scenario())


# ---------------------------------------------------------------- Gemini failures are fatal

def test_gemini_failure_before_any_text_is_one_fatal_llm_error_and_no_speech():
    llm, tts = FakeProvider(chunks=REPLY, stream_error=LLMAuthError(), error_after=0), FakeTTSProvider()

    async def scenario():
        app = make_app(llm, tts=tts)
        call = await connect(app)
        call.send_json({"type": "text", "text": "hi"})
        items = await call.items()
        await call.finished()
        assert types(items) == ["ready", "error"]
        error = items[-1]
        assert (error["stage"], error["code"], error["fatal"]) == ("llm", "llm_authentication_failed", True)
        assert tts.started == 0 and call.close_code == 1011
        await assert_clean(app, llm, tts)

    run(scenario())


def test_gemini_failure_mid_reply_is_fatal_and_the_unfinished_reply_is_not_stored():
    llm = FakeProvider(chunks=["Pehla vaakya. ", "Doosra"], stream_error=LLMAuthError(), error_after=1)

    async def scenario():
        app = make_app(llm)
        config = {"type": "config", "session_id": "llm-fail-1"}
        items = await text_turn(app, "pehla", config)
        assert terminal_events(items)[0]["stage"] == "llm" and not events(items, "done")
        assert len(terminal_events(items)) == 1
        llm2 = llm.calls  # the failed reply must not appear in the next turn's history
        llm.stream_error = None
        await text_turn(app, "doosra", config)
        assert [m.text for m in llm2[1][1]] == ["doosra"]
        await assert_clean(app, llm)

    run(scenario())


# ---------------------------------------------------------------- configuration and protocol errors

def test_missing_gemini_or_tts_credentials_are_fatal_errors_before_any_work():
    async def scenario():
        no_llm = make_app(None)
        items = await text_turn(no_llm)
        assert types(items) == ["error"] and (items[0]["stage"], items[0]["code"]) == ("llm", "llm_not_configured")

        tts = FakeTTSProvider()
        no_tts_app = create_app(make_settings(), llm_provider=FakeProvider(chunks=REPLY), tts_provider=None)
        items = await text_turn(no_tts_app)
        assert types(items) == ["error"] and (items[0]["stage"], items[0]["code"]) == ("tts", "tts_not_configured")
        assert tts.started == 0

    run(scenario())


def test_text_turns_work_without_stt_but_audio_turns_report_stt_not_configured():
    llm = FakeProvider(chunks=["Ek vaakya. "])

    async def scenario():
        app = create_app(make_settings(), llm_provider=llm, stt_provider=None, tts_provider=FakeTTSProvider())
        assert events(await text_turn(app), "done")  # no Deepgram key needed for text
        call = await connect(app, {"type": "config", "sample_rate": 16000})
        call.send_bytes(CHUNK)
        items = await call.items()
        assert (items[-1]["stage"], items[-1]["code"], items[-1]["fatal"]) == ("stt", "stt_not_configured", True)

    run(scenario())


@pytest.mark.parametrize(
    "config",
    [
        {"type": "config", "language": "klingon"},
        {"type": "config", "unknown": 1},
        {"type": "config", "session_id": "bad id!"},
        {"type": "config", "sample_rate": "16000"},
        {"type": "config", "sample_rate": 12345},
        {"type": "config", "channels": 2},
        {"type": "hello"},
        {},
    ],
)
def test_invalid_config_is_a_fatal_protocol_error_that_never_echoes_values(config):
    async def scenario():
        call = await connect(make_app(), config)
        items = await call.items()
        await call.finished()
        assert len(items) == 1 and items[0]["type"] == "error"
        error = items[0]
        assert (error["stage"], error["code"], error["fatal"]) == ("protocol", "voice_invalid_config", True)
        assert call.close_code == 1008 and all(d["field"] for d in error["details"])
        for value in ("klingon", "bad id!", "12345"):
            assert value not in str(error)

    run(scenario())


def test_first_message_must_be_a_config_text_frame():
    async def scenario():
        call = await connect(make_app(), config=None)
        call.send_bytes(CHUNK)
        items = await call.items()
        assert items[0]["code"] == "voice_invalid_config"
        call = await connect(make_app(), config=None)
        call.send_text("not json")
        assert (await call.items())[0]["code"] == "voice_invalid_config"

    run(scenario())


@pytest.mark.parametrize(
    "message",
    [
        {"type": "nope"},
        {"type": "text"},
        {"type": "text", "text": "   "},
        {"type": "text", "text": "x" * 2001},
        {"type": "text", "text": 5},
        {"type": "text", "text": "ok", "extra": 1},
        {"type": "end"},
    ],
)
def test_invalid_first_message_after_config_is_a_protocol_error(message):
    llm = FakeProvider(chunks=REPLY)

    async def scenario():
        call = await connect(make_app(llm))
        call.send_json(message)
        items = await call.items()
        error = items[-1]
        assert (error["stage"], error["code"], error["fatal"]) == ("protocol", "voice_invalid_message", True)
        assert llm.streams_started == 0 and call.close_code == 1008

    run(scenario())


def test_silence_after_config_ends_with_an_idle_timeout():
    async def scenario():
        call = await connect(make_app(stt_idle_timeout_seconds=0.15))
        items = await call.items()
        assert (items[-1]["code"], items[-1]["stage"]) == ("voice_idle_timeout", "protocol")

    run(scenario())


def test_browser_origin_allow_list_is_enforced_like_the_stt_endpoint():
    async def scenario():
        app = make_app(stt_allowed_origins="http://good.test")
        bad = WsCall(app, headers={"origin": "http://evil.test"}, path="/voice/stream")
        assert not await bad.wait_accepted() and bad.close_code == 1008
        good = await connect(app, headers={"origin": "http://good.test"})
        good.send_json({"type": "text", "text": "hi"})
        assert events(await good.items(), "done")
        assert events(await text_turn(app), "done")  # no Origin header (scripts, curl): allowed

    run(scenario())


# ---------------------------------------------------------------- audio turn (raw PCM16 + the existing STT protocol)

def test_audio_turn_transcribes_then_answers_and_releases_stt_before_gemini_starts():
    gate = asyncio.Event()
    stt = FakeSTTProvider(
        on_chunk={1: [partial("namaste")], 2: [partial("namaste duniya")], 3: [final("namaste duniya", speech_final=True)]},
        on_finish=[final("kaise ho", start=1.0)],
    )
    llm, tts = FakeProvider(chunks=["Theek hoon. "], chunk_gates=[gate]), FakeTTSProvider([b"AAA"])

    async def scenario():
        app = make_app(llm, stt, tts)
        call = await connect(app, {"type": "config", "language": "hinglish", "sample_rate": 16000})
        for _ in range(3):
            call.send_bytes(CHUNK)
        call.send_json({"type": "end"})
        first = []
        while len(events(first, "final")) < 2:
            first.append(await call.next_item())
        # Gemini is now waiting on its gate: the STT session is closed and its slot is free
        await wait_until(lambda: llm.streams_started == 1)
        assert stt.last.closed and app.state.stt_service.limiter.in_use == 0
        assert app.state.chat_service.limiter.in_use == 1
        gate.set()
        items = first + await call.items()
        await call.finished()

        assert types(items)[:2] == ["ready", "partial"]
        assert [(e["type"], e["seq"], e["text"]) for e in events(items) if e["type"] in ("partial", "final")] == [
            ("partial", 1, "namaste"), ("partial", 2, "namaste duniya"), ("final", 3, "namaste duniya"), ("final", 4, "kaise ho"),
        ]
        assert set(events(items, "final")[0]) == {"type", "seq", "text", "start", "duration", "speech_final", "confidence"}
        assert llm.calls[0][1][-1].text == "namaste duniya kaise ho"  # the finals, joined in order, are the user's message
        assert stt.opened[0][0] == "hinglish" and stt.opened[0][1].sample_rate == 16000
        assert stt.last.audio_bytes == 3 * len(CHUNK) and stt.last.finished
        done = events(items, "done")[0]
        assert done["transcript_ms"] is not None and done["audio_complete"] is True and len(terminal_events(items)) == 1
        await assert_clean(app, llm, tts)

    run(scenario())


def test_audio_without_a_sample_rate_is_a_config_error():
    async def scenario():
        call = await connect(make_app())
        call.send_bytes(CHUNK)
        items = await call.items()
        assert (items[-1]["code"], items[-1]["stage"]) == ("voice_invalid_config", "protocol")

    run(scenario())


def test_audio_with_no_recognised_speech_is_a_stt_error_and_gemini_is_not_called():
    stt, llm = FakeSTTProvider(), FakeProvider(chunks=REPLY)

    async def scenario():
        app = make_app(llm, stt)
        call = await connect(app, {"type": "config", "sample_rate": 16000})
        call.send_bytes(CHUNK)
        call.send_json({"type": "end"})
        items = await call.items()
        assert (items[-1]["stage"], items[-1]["code"], items[-1]["fatal"]) == ("stt", "voice_no_speech", True)
        assert llm.streams_started == 0 and stt.last.closed
        await assert_clean(app, llm)

    run(scenario())


@pytest.mark.parametrize(
    "frame, code",
    [
        (b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32, "stt_invalid_audio"),  # a WAV header sent as PCM
        (b"\x01\x00\x02", "stt_invalid_audio"),  # odd number of bytes
        (b"", "stt_invalid_audio"),
        (b"\x00\x00" * 40_000, "stt_limit_exceeded"),  # larger than STT_MAX_CHUNK_BYTES
    ],
    ids=["wav-header", "odd-byte-count", "empty-frame", "oversized-frame"],
)
def test_bad_audio_frames_are_rejected_with_stt_errors(frame, code):
    stt, llm = FakeSTTProvider(), FakeProvider(chunks=REPLY)

    async def scenario():
        app = make_app(llm, stt)
        call = await connect(app, {"type": "config", "sample_rate": 16000})
        call.send_bytes(frame)
        items = await call.items()
        assert (items[-1]["stage"], items[-1]["code"]) == ("stt", code)
        assert llm.streams_started == 0
        await assert_clean(app, llm)

    run(scenario())


def test_stt_provider_failure_is_a_fatal_stt_error():
    from app.errors import SttAuthError

    stt, llm = FakeSTTProvider(error_at_chunk=1, error=SttAuthError()), FakeProvider(chunks=REPLY)

    async def scenario():
        app = make_app(llm, stt)
        call = await connect(app, {"type": "config", "sample_rate": 16000})
        call.send_bytes(CHUNK)
        items = await call.items()
        assert (items[-1]["stage"], items[-1]["code"], items[-1]["fatal"]) == ("stt", "stt_authentication_failed", True)
        assert llm.streams_started == 0 and stt.last.closed
        await assert_clean(app, llm)

    run(scenario())


def test_an_overlong_transcript_is_rejected_instead_of_truncated():
    stt = FakeSTTProvider(on_finish=[final("a" * 2001)])

    async def scenario():
        call = await connect(make_app(stt=stt), {"type": "config", "sample_rate": 16000})
        call.send_bytes(CHUNK)
        call.send_json({"type": "end"})
        items = await call.items()
        assert (items[-1]["stage"], items[-1]["code"]) == ("stt", "voice_transcript_too_long")

    run(scenario())


# ---------------------------------------------------------------- disconnects, timeouts, limits: everything is released

def test_disconnect_while_gemini_is_generating_cancels_it_and_releases_everything():
    llm = FakeProvider(chunks=["Ek. ", "Do. "], hang_after=1)
    tts = FakeTTSProvider([b"AAA"])

    async def scenario():
        app = make_app(llm, tts=tts)
        call = await connect(app, {"type": "config", "session_id": "gone-1"})
        call.send_json({"type": "text", "text": "hi"})
        while not (isinstance(item := await call.next_item(), dict) and item["type"] == "audio_end"):
            pass
        call.disconnect()
        await call.finished()
        assert llm.stream_cancelled and llm.streams_closed == 1
        await assert_clean(app, llm, tts)
        llm.hang_after = None  # the next turn must be able to finish
        await text_turn(app, "again", {"type": "config", "session_id": "gone-1"})
        assert [m.text for m in llm.calls[1][1]] == ["again"]  # the cancelled reply was never stored

    run(scenario())


def test_disconnect_while_speech_is_being_generated_cancels_both_upstreams():
    llm = FakeProvider(chunks=["Ek vaakya. ", "Doosra vaakya. "], hang_after=1)
    tts = FakeTTSProvider([b"AAA", b"BBB"], hang_after=1)

    async def scenario():
        app = make_app(llm, tts=tts)
        call = await connect(app)
        call.send_json({"type": "text", "text": "hi"})
        while not (isinstance(item := await call.next_item(), bytes)):
            pass
        assert item == b"AAA"
        call.disconnect()
        await call.finished()
        assert tts.cancelled and tts.closed == 1 and llm.stream_cancelled
        await assert_clean(app, llm, tts)

    run(scenario())


def test_disconnect_while_listening_closes_the_stt_session_and_releases_its_slot():
    stt, llm = FakeSTTProvider(), FakeProvider(chunks=REPLY)

    async def scenario():
        app = make_app(llm, stt)
        call = await connect(app, {"type": "config", "sample_rate": 16000})
        call.send_bytes(CHUNK)
        await wait_until(lambda: stt.sessions and stt.last.audio_bytes == len(CHUNK))
        assert app.state.stt_service.limiter.in_use == 1 and app.state.voice_service.limiter.in_use == 1
        call.disconnect()
        await call.finished()
        assert stt.last.closed and llm.streams_started == 0
        await assert_clean(app, llm)

    run(scenario())


def test_disconnect_before_the_config_does_no_work():
    llm = FakeProvider(chunks=REPLY)

    async def scenario():
        app = make_app(llm)
        call = await connect(app, config=None)
        call.disconnect()
        await call.finished()
        assert llm.streams_started == 0
        await assert_clean(app, llm)

    run(scenario())


def test_a_turn_that_exceeds_the_turn_timeout_is_stopped_with_one_fatal_error():
    llm = FakeProvider(chunks=["Ek vaakya. ", "Do"], hang_after=1)
    tts = FakeTTSProvider([b"AAA"])

    async def scenario():
        app = make_app(llm, tts=tts, voice_turn_timeout_seconds=0.3)
        call = await connect(app)
        call.send_json({"type": "text", "text": "hi"})
        items = await call.items()
        await call.finished()
        assert (items[-1]["stage"], items[-1]["code"], items[-1]["fatal"]) == ("server", "voice_turn_timeout", True)
        assert len(terminal_events(items)) == 1 and call.close_code == 1011
        assert llm.stream_cancelled
        await assert_clean(app, llm, tts)

    run(scenario())


def test_turn_concurrency_limit_rejects_extra_turns_and_the_slot_comes_back():
    gate = asyncio.Event()
    llm = FakeProvider(chunks=["Ek vaakya. "], chunk_gates=[gate])

    async def scenario():
        app = make_app(llm, voice_max_concurrent_turns=1)
        first = await connect(app)
        first.send_json({"type": "text", "text": "hi"})
        await wait_until(lambda: app.state.voice_service.limiter.in_use == 1)

        second = WsCall(app, path="/voice/stream")
        assert await second.wait_accepted()
        items = await second.items()
        assert (items[0]["stage"], items[0]["code"], items[0]["fatal"]) == ("server", "voice_capacity_reached", True)
        assert second.close_code == 1013 and llm.streams_started == 1

        gate.set()
        assert events(await first.items(), "done")
        await wait_until(lambda: app.state.voice_service.limiter.in_use == 0)
        assert events(await text_turn(app), "done")  # the slot is free again
        await assert_clean(app, llm)

    run(scenario())


def test_stage_limiters_are_independent_of_each_other_and_of_the_turn_limiter():
    app = make_app(voice_max_concurrent_turns=7, llm_max_concurrent_generations=5, tts_max_concurrent_requests=3,
                   stt_max_concurrent_streams=2)
    limiters = [app.state.voice_service.limiter, app.state.chat_service.limiter, app.state.tts_service.limiter,
                app.state.stt_service.limiter]
    assert len({id(x) for x in limiters}) == 4
    assert [x.max_concurrent for x in limiters] == [7, 5, 3, 2]


def test_a_stalled_client_is_dropped_and_everything_is_released():
    llm, tts = FakeProvider(chunks=[f"Vaakya {i}. " for i in range(100)]), FakeTTSProvider([b"A" * 100])

    async def scenario():
        app = make_app(llm, tts=tts, stt_send_timeout_seconds=0.15)
        call = await connect(app, stall_after_sends=3)  # stops reading after three messages
        call.send_json({"type": "text", "text": "hi"})
        await wait_until(lambda: llm.stream_cancelled)  # the server gives up on its own, within the send timeout
        assert llm.chunks_sent < 100
        await wait_until(lambda: app.state.voice_service.limiter.in_use == 0 and app.state.chat_service.limiter.in_use == 0
                         and app.state.tts_service.limiter.in_use == 0)
        call.task.cancel()
        await asyncio.gather(call.task, return_exceptions=True)

    run(scenario())


# ---------------------------------------------------------------- privacy: nothing sensitive in logs

def test_logs_never_contain_user_text_transcripts_replies_audio_keys_or_provider_details(caplog):
    caplog.set_level(logging.DEBUG)
    secret_error = RuntimeError(f"provider said: {SECRET_TEXT} {SECRET_REPLY} {SECRET_KEY}")
    ok_llm = FakeProvider(chunks=[SECRET_REPLY + " "])
    failing_llm = FakeProvider(chunks=[SECRET_REPLY], stream_error=secret_error, error_after=0)
    failing_tts = FakeTTSProvider([b"AUDIO-BYTES-SECRET"], error=RuntimeError(f"{SECRET_REPLY} {SECRET_KEY}"))
    stt = FakeSTTProvider(on_finish=[final(SECRET_TEXT)])

    async def scenario():
        for llm, tts in ((ok_llm, FakeTTSProvider([b"AUDIO-BYTES-SECRET"])), (failing_llm, FakeTTSProvider()), (ok_llm, failing_tts)):
            app = make_app(llm, stt, tts, deepgram_api_key=SECRET_KEY)
            items = await text_turn(app, SECRET_TEXT)
            assert SECRET_KEY not in str(items) and "provider said" not in str(items)  # nor in what the client sees
        app = make_app(ok_llm, stt)
        call = await connect(app, {"type": "config", "sample_rate": 16000})
        call.send_bytes(CHUNK)
        call.send_json({"type": "end"})
        await call.items()

    run(scenario())
    assert "voice turn finished" in caplog.text
    for secret in (SECRET_TEXT, SECRET_REPLY, SECRET_KEY, "AUDIO-BYTES-SECRET", "provider said"):
        assert secret not in caplog.text


def test_sentences_are_never_longer_than_what_tts_accepts():
    long_sentence = "alpha beta gamma delta " * 8  # 184 characters with no sentence end
    llm, tts = FakeProvider(chunks=[long_sentence]), FakeTTSProvider([b"A"])

    async def scenario():
        app = make_app(llm, tts=tts, tts_max_text_chars=60, voice_max_sentence_chars=300)  # TTS is the tighter limit
        items = await text_turn(app)
        assert events(items, "done")[0]["audio_complete"] is True and len(tts.calls) > 1
        assert all(len(text) <= 60 for text, _ in tts.calls)
        assert " ".join(text for text, _ in tts.calls).split() == long_sentence.split()  # nothing lost

    run(scenario())


# ---------------------------------------------------------------- configuration

def test_voice_settings_defaults_and_validation(monkeypatch):
    for name in ("VOICE_MAX_CONCURRENT_TURNS", "VOICE_TURN_TIMEOUT_SECONDS", "VOICE_SENTENCE_QUEUE_SIZE", "VOICE_MAX_SENTENCE_CHARS"):
        monkeypatch.delenv(name, raising=False)
    s = make_settings()
    assert (s.voice_max_concurrent_turns, s.voice_turn_timeout_seconds, s.voice_sentence_queue_size, s.voice_max_sentence_chars) == (4, 90.0, 3, 300)
    from pydantic import ValidationError

    for bad in ({"voice_max_concurrent_turns": 0}, {"voice_turn_timeout_seconds": 0}, {"voice_sentence_queue_size": 0},
                {"voice_max_sentence_chars": 5}):
        with pytest.raises(ValidationError):
            make_settings(**bad)
    monkeypatch.setenv("VOICE_SENTENCE_QUEUE_SIZE", "5")
    from app.config import Settings

    assert Settings(_env_file=None).voice_sentence_queue_size == 5  # env values are strings: they must parse
