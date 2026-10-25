"""Regression tests for agent-specific prompts, language mapping, voice selection, and session isolation."""

import json
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.prompts import build_system_instruction
from tests.asgi_client import connect_ws
from tests.conftest import FakeProvider, make_settings
from tests.stt_fakes import FakeSTTProvider
from tests.tts_fakes import FakeTTSProvider


def test_build_system_instruction_with_and_without_agent_prompt():
    # Without custom prompt: returns default base prompt
    base_en = build_system_instruction("english")
    assert "You are AwaazAI" in base_en
    assert "reply in clear, simple English" in base_en

    base_hi = build_system_instruction("hindi")
    assert "You are AwaazAI" in base_hi
    assert "reply in Hindi, written in Devanagari script" in base_hi

    base_hinglish = build_system_instruction("hinglish")
    assert "You are AwaazAI" in base_hinglish
    assert "reply in natural Hinglish" in base_hinglish

    # With custom agent prompt: combines custom prompt with voice constraints and language rules
    custom = "You are Dr. Sharma's dental receptionist. Only answer dental appointment questions."
    agent_en = build_system_instruction("english", custom)
    assert custom in agent_en
    assert "Voice formatting rules:" in agent_en
    assert "reply in clear, simple English" in agent_en

    agent_hi = build_system_instruction("hindi", custom)
    assert custom in agent_hi
    assert "Voice formatting rules:" in agent_hi
    assert "reply in Hindi, written in Devanagari script" in agent_hi

    agent_hinglish = build_system_instruction("hinglish", custom)
    assert custom in agent_hinglish
    assert "Voice formatting rules:" in agent_hinglish
    assert "reply in natural Hinglish" in agent_hinglish


def test_create_voice_session_endpoint():
    settings = make_settings()
    llm = FakeProvider()
    tts = FakeTTSProvider()
    stt = FakeSTTProvider()
    app = create_app(settings, llm_provider=llm, stt_provider=stt, tts_provider=tts)

    with TestClient(app) as client:
        # Create session with agent configuration
        resp = client.post(
            "/voice/session",
            json={
                "session_id": "test-session-1234",
                "agent_id": "agent-uuid-5678",
                "system_prompt": "You are a customer support agent for Acme Corp.",
                "language": "hinglish",
                "voice": "aura-2-thalia-en",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == "test-session-1234"
        assert body["agent_id"] == "agent-uuid-5678"
        assert body["language"] == "hinglish"
        assert body["voice"] == "aura-2-thalia-en"

        # Verify session is bound in SessionStore
        session = app.state.chat_service._store.get("test-session-1234")
        assert session is not None
        assert session.system_prompt == "You are a customer support agent for Acme Corp."
        assert session.voice == "aura-2-thalia-en"
        assert session.language == "hinglish"


def test_create_voice_session_rejects_invalid_voice():
    settings = make_settings()
    app = create_app(settings, llm_provider=FakeProvider(), stt_provider=FakeSTTProvider(), tts_provider=FakeTTSProvider())

    with TestClient(app) as client:
        resp = client.post(
            "/voice/session",
            json={"session_id": "invalid-voice-sid", "voice": "unknown-nonexistent-voice"},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "tts_invalid_voice"


def test_agent_specific_prompt_applied_in_voice_turn():
    settings = make_settings()
    llm = FakeProvider(chunks=["Hello from Acme support."])
    tts = FakeTTSProvider([b"MP3-BYTES"])
    app = create_app(settings, llm_provider=llm, stt_provider=FakeSTTProvider(), tts_provider=tts)

    agent_prompt = "You are a specialized legal advisor. Only speak about contract law."
    # Pre-bind session
    app.state.voice_service.create_session(
        session_id="legal-session-01",
        system_prompt=agent_prompt,
        language="english",
    )

    with connect_ws(app) as ws:
        ws.send_json({"type": "config", "session_id": "legal-session-01", "language": "english"})
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["session_id"] == "legal-session-01"

        ws.send_json({"type": "text", "text": "What is an NDA?"})
        done = None
        while True:
            msg = ws.receive()
            if isinstance(msg, dict) and msg.get("type") == "done":
                done = msg
                break
        assert done is not None

    # Check LLM call: system_instruction must include the agent's custom prompt!
    assert len(llm.calls) == 1
    system_instruction, messages = llm.calls[0]
    assert agent_prompt in system_instruction
    assert "Voice formatting rules:" in system_instruction
    assert "reply in clear, simple English" in system_instruction


def test_voice_selection_applied_in_voice_turn():
    settings = make_settings(deepgram_tts_voices="aura-2-custom-en")
    llm = FakeProvider(chunks=["Reply voice test."])
    tts = FakeTTSProvider([b"AUDIO-DATA"])
    app = create_app(settings, llm_provider=llm, stt_provider=FakeSTTProvider(), tts_provider=tts)

    app.state.voice_service.create_session(
        session_id="voice-session-02",
        system_prompt="Short prompt.",
        language="english",
        voice="aura-2-custom-en",
    )

    with connect_ws(app) as ws:
        ws.send_json({"type": "config", "session_id": "voice-session-02", "language": "english"})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "text", "text": "Testing voice selection"})
        while True:
            msg = ws.receive()
            if isinstance(msg, dict) and msg.get("type") == "done":
                break

    # Check TTS call: must use the selected voice!
    assert len(tts.calls) == 1
    text, voice = tts.calls[0]
    assert voice == "aura-2-custom-en"


def test_session_isolation_between_agents():
    settings = make_settings()
    llm = FakeProvider(chunks=["Agent reply."])
    tts = FakeTTSProvider([b"AUDIO"])
    app = create_app(settings, llm_provider=llm, stt_provider=FakeSTTProvider(), tts_provider=tts)

    # Session 1: Medical Agent
    app.state.voice_service.create_session(
        session_id="session-medical",
        system_prompt="Medical doctor persona.",
        language="english",
    )

    # Session 2: Financial Agent
    app.state.voice_service.create_session(
        session_id="session-finance",
        system_prompt="Financial advisor persona.",
        language="hindi",
    )

    # Run turn on medical session
    with connect_ws(app) as ws:
        ws.send_json({"type": "config", "session_id": "session-medical", "language": "english"})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "text", "text": "I have a headache."})
        while ws.receive_json().get("type") != "done":
            pass

    # Run turn on finance session
    with connect_ws(app) as ws:
        ws.send_json({"type": "config", "session_id": "session-finance", "language": "hindi"})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "text", "text": "Mutual fund advice."})
        while ws.receive_json().get("type") != "done":
            pass

    assert len(llm.calls) == 2
    # Turn 1: medical prompt
    instruction_1, msgs_1 = llm.calls[0]
    assert "Medical doctor persona" in instruction_1
    assert "Financial advisor persona" not in instruction_1
    assert msgs_1[-1].text == "I have a headache."

    # Turn 2: finance prompt
    instruction_2, msgs_2 = llm.calls[1]
    assert "Financial advisor persona" in instruction_2
    assert "Medical doctor persona" not in instruction_2
    assert msgs_2[-1].text == "Mutual fund advice."
    # Complete history isolation: Turn 2 history does NOT contain Turn 1 messages
    assert not any(m.text == "I have a headache." for m in msgs_2)
