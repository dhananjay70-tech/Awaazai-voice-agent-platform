"""DeepgramProvider against a local fake Deepgram WebSocket (real sockets, real `websockets` library, no internet)."""

import asyncio
import json
import logging

import pytest

from app.logging_setup import configure_logging
from app.errors import (
    SttAuthError,
    SttBadResponseError,
    SttInvalidAudioError,
    SttProviderError,
    SttRateLimitError,
    SttTimeoutError,
    SttUnavailableError,
)
from app.stt.base import AudioFormat
from app.stt.deepgram import DeepgramProvider
from tests.fake_deepgram import FakeDeepgramServer, results

KEY = "fake-deepgram-key-NOT-A-REAL-KEY-0123456789"
AUDIO = AudioFormat("linear16", 16000, 1)
CHUNK = b"\x01\x00" * 160  # 10 ms of 16 kHz mono PCM16


def provider_for(server, **overrides):
    values = dict(
        api_key=KEY, model="nova-3", url=server.url,
        language_codes={"english": "en", "hindi": "hi", "hinglish": "multi"},
        endpointing_ms=300, connect_timeout_seconds=3,
    )
    values.update(overrides)
    return DeepgramProvider(**values)


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 15))


async def collect(session):
    return [event async for event in session.events()]


# ---------------------------------------------------------------- handshake: URL, parameters, authentication

def test_handshake_follows_the_documented_protocol():
    with FakeDeepgramServer(on_close_stream=[]) as server:
        async def scenario():
            session = await provider_for(server).open(language="hindi", audio=AudioFormat("linear16", 24000, 1))
            await session.finish()
            await collect(session)
            await session.aclose()

        run(scenario())
    handshake = server.handshakes[0]
    assert handshake["path"] == "/v1/listen"
    assert handshake["authorization"] == f"Token {KEY}"  # documented scheme: "Authorization: Token <API_KEY>"
    assert handshake["query"] == {
        "model": "nova-3", "language": "hi", "encoding": "linear16", "sample_rate": "24000", "channels": "1",
        "interim_results": "true", "endpointing": "300", "punctuate": "true",
    }


@pytest.mark.parametrize("language,code", [("english", "en"), ("hindi", "hi"), ("hinglish", "multi")])
def test_language_names_map_to_deepgram_codes(language, code):
    with FakeDeepgramServer() as server:
        async def scenario():
            session = await provider_for(server).open(language=language, audio=AUDIO)
            await session.aclose()

        run(scenario())
    assert server.handshakes[0]["query"]["language"] == code


def test_configured_language_mapping_is_used():
    with FakeDeepgramServer() as server:
        async def scenario():
            provider = provider_for(server, language_codes={"english": "en-IN", "hindi": "hi", "hinglish": "hi"})
            for language in ("english", "hinglish"):
                session = await provider.open(language=language, audio=AUDIO)
                await session.aclose()

        run(scenario())
    assert [h["query"]["language"] for h in server.handshakes] == ["en-IN", "hi"]


# ---------------------------------------------------------------- audio and control messages

def test_audio_frames_are_forwarded_unchanged_and_finish_sends_finalize_then_closestream():
    with FakeDeepgramServer() as server:
        async def scenario():
            session = await provider_for(server).open(language="english", audio=AUDIO)
            for i in range(3):
                await session.send_audio(CHUNK + bytes([i, 0]))
            await session.finish()
            await collect(session)  # the server closes after CloseStream
            await session.aclose()

        run(scenario())
    assert server.audio_frames == [CHUNK + bytes([i, 0]) for i in range(3)]
    assert server.control_messages == [{"type": "Finalize"}, {"type": "CloseStream"}]  # exact documented payloads


# ---------------------------------------------------------------- results parsing

def test_partial_and_final_results_are_parsed():
    script = {
        1: [results("namaste", start=0.0, duration=0.4)],
        2: [results("namaste duniya", is_final=True, speech_final=True, start=0.0, duration=1.2, confidence=0.91)],
    }
    with FakeDeepgramServer(on_audio=script) as server:
        async def scenario():
            session = await provider_for(server).open(language="hinglish", audio=AUDIO)
            await session.send_audio(CHUNK)
            await session.send_audio(CHUNK)
            await session.finish()
            events = await collect(session)
            await session.aclose()
            return events

        events = run(scenario())
    assert [(e.kind, e.text, e.speech_final) for e in events] == [("partial", "namaste", False), ("final", "namaste duniya", True)]
    assert events[1].start == 0.0 and events[1].duration == 1.2 and events[1].confidence == 0.91


def test_non_transcript_messages_are_ignored():
    noise = [
        {"type": "Metadata", "request_id": "r"}, {"type": "SpeechStarted", "channel": [0], "timestamp": 1.0},
        {"type": "UtteranceEnd", "channel": [0, 1], "last_word_end": 2.0}, {"type": "SomethingNewInTheFuture"},
        {"type": "Error", "variant": "SchemaError", "description": "SENSITIVE-description", "message": "SENSITIVE-echo"},
        results("   "), results("", is_final=True),  # silence: empty transcripts
    ]
    with FakeDeepgramServer(on_audio={1: noise + [results("hello", is_final=True)]}) as server:
        async def scenario():
            session = await provider_for(server).open(language="english", audio=AUDIO)
            await session.send_audio(CHUNK)
            await session.finish()
            events = await collect(session)
            await session.aclose()
            return events

        events = run(scenario())
    assert [(e.kind, e.text) for e in events] == [("final", "hello")]


def test_non_fatal_provider_error_is_logged_without_its_content(caplog):
    error = {"type": "Error", "variant": "SchemaError", "description": "SENSITIVE-description", "message": "SENSITIVE-echo"}
    with FakeDeepgramServer(on_audio={1: [error]}) as server:
        async def scenario():
            session = await provider_for(server).open(language="english", audio=AUDIO)
            await session.send_audio(CHUNK)
            await session.finish()
            await collect(session)
            await session.aclose()

        configure_logging("DEBUG")  # the worst case: an operator running with LOG_LEVEL=DEBUG
        with caplog.at_level(logging.DEBUG):
            run(scenario())
    assert "variant=SchemaError" in caplog.text and "SENSITIVE" not in caplog.text


BAD_MESSAGES = {
    "not json": "this is not json",
    "json but not an object": "[1, 2, 3]",
    "results without channel": json.dumps({"type": "Results", "is_final": True}),
    "results with empty alternatives": json.dumps({"type": "Results", "is_final": True, "channel": {"alternatives": []}}),
    "transcript not a string": json.dumps({"type": "Results", "is_final": True, "channel": {"alternatives": [{"transcript": 5}]}}),
    "is_final not a bool": json.dumps({"type": "Results", "is_final": "yes", "channel": {"alternatives": [{"transcript": "x"}]}}),
    "speech_final not a bool": json.dumps({"type": "Results", "is_final": True, "speech_final": 1, "channel": {"alternatives": [{"transcript": "x"}]}}),
    "start is a string": json.dumps({"type": "Results", "is_final": True, "start": "0", "channel": {"alternatives": [{"transcript": "x"}]}}),
    "duration is NaN": '{"type":"Results","is_final":true,"duration":NaN,"channel":{"alternatives":[{"transcript":"x"}]}}',
    "binary frame from the server": b"\x00\x01\x02",
}


@pytest.mark.parametrize("name", list(BAD_MESSAGES))
def test_malformed_messages_raise_bad_response(name):
    with FakeDeepgramServer(on_audio={1: [BAD_MESSAGES[name]]}) as server:
        async def scenario():
            session = await provider_for(server).open(language="english", audio=AUDIO)
            await session.send_audio(CHUNK)
            try:
                await collect(session)
            finally:
                await session.aclose()

        with pytest.raises(SttBadResponseError):
            run(scenario())


# ---------------------------------------------------------------- failures: handshake

@pytest.mark.parametrize(
    "status,expected",
    [(401, SttAuthError), (403, SttAuthError), (429, SttRateLimitError), (500, SttUnavailableError),
     (503, SttUnavailableError), (400, SttProviderError), (404, SttProviderError)],
)
def test_handshake_rejections_are_translated(status, expected, caplog):
    with FakeDeepgramServer(reject_status=status) as server:
        configure_logging("DEBUG")  # the worst case: an operator running with LOG_LEVEL=DEBUG
        with caplog.at_level(logging.DEBUG), pytest.raises(expected) as info:
            run(provider_for(server).open(language="english", audio=AUDIO))
    assert type(info.value) is expected and info.value.__cause__ is None
    assert KEY not in caplog.text and KEY not in str(info.value)
    assert f"http_status={status}" in caplog.text  # category and status only


def test_connection_refused_is_unavailable():
    with FakeDeepgramServer() as server:
        url = server.url
    with pytest.raises(SttUnavailableError):  # the server has stopped: nothing is listening
        run(provider_for(server, url=url).open(language="english", audio=AUDIO))


def test_connect_timeout_is_reported_as_timeout():
    async def scenario():
        async def accept_and_stall(reader, writer):  # accepts TCP but never answers the WebSocket handshake
            await asyncio.sleep(5)

        server = await asyncio.start_server(accept_and_stall, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            provider = DeepgramProvider(api_key=KEY, model="nova-3", url=f"ws://127.0.0.1:{port}/v1/listen",
                                        language_codes={"english": "en", "hindi": "hi", "hinglish": "multi"},
                                        endpointing_ms=300, connect_timeout_seconds=0.3)
            await provider.open(language="english", audio=AUDIO)
        finally:
            server.close()

    with pytest.raises(SttTimeoutError):
        run(scenario())


# ---------------------------------------------------------------- failures: mid-stream

@pytest.mark.parametrize(
    "code,expected",
    [(1008, SttInvalidAudioError), (1011, SttProviderError), (1013, SttUnavailableError), (1001, SttUnavailableError), (1002, SttProviderError)],
)
def test_provider_close_codes_are_translated(code, expected):
    with FakeDeepgramServer(on_audio={1: [results("partial text")]}, close_after_audio=(1, code)) as server:
        async def scenario():
            session = await provider_for(server).open(language="english", audio=AUDIO)
            await session.send_audio(CHUNK)
            seen = []
            try:
                async for event in session.events():
                    seen.append(event)
            finally:
                await session.aclose()
            return seen

        with pytest.raises(expected):
            run(scenario())


def test_normal_close_before_the_client_finished_is_an_error_when_sending():
    with FakeDeepgramServer(close_after_audio=(1, 1000)) as server:
        async def scenario():
            session = await provider_for(server).open(language="english", audio=AUDIO)
            await session.send_audio(CHUNK)
            await asyncio.sleep(0.3)  # the server has closed by now
            try:
                await session.send_audio(CHUNK)
            finally:
                await session.aclose()

        with pytest.raises(SttProviderError):
            run(scenario())


# ---------------------------------------------------------------- cleanup: the connection really closes

def test_aclose_closes_the_connection_and_is_idempotent():
    with FakeDeepgramServer() as server:
        async def scenario():
            session = await provider_for(server).open(language="english", audio=AUDIO)
            await session.send_audio(CHUNK)
            await session.aclose()
            await session.aclose()  # second call is harmless

        run(scenario())
        assert server.client_gone.wait(3), "the server never saw the client's connection close"


def test_cancelling_the_event_reader_and_closing_releases_the_connection():
    with FakeDeepgramServer() as server:
        async def scenario():
            session = await provider_for(server).open(language="english", audio=AUDIO)
            reader = asyncio.create_task(collect(session))  # waiting for results that never come
            await asyncio.sleep(0.2)
            reader.cancel()
            with pytest.raises(asyncio.CancelledError):
                await reader
            await session.aclose()

        run(scenario())
        assert server.client_gone.wait(3)


def test_the_api_key_is_not_in_the_provider_repr():
    with FakeDeepgramServer() as server:
        assert KEY not in repr(provider_for(server)) and KEY not in str(provider_for(server).__dict__.get("_url", ""))
