import uuid

from fastapi import APIRouter, Request, WebSocket

from app.voice.protocol import VoiceSessionCreateRequest, VoiceSessionResponse
from app.voice.service import VoiceStreamService

router = APIRouter(tags=["voice"])


@router.post("/voice/session", response_model=VoiceSessionResponse)
async def create_voice_session(payload: VoiceSessionCreateRequest, request: Request) -> VoiceSessionResponse:
    """Pre-configure or bind a voice session with agent instructions, language, and voice."""
    service: VoiceStreamService = request.app.state.voice_service
    result = service.create_session(
        session_id=payload.session_id,
        agent_id=payload.agent_id,
        system_prompt=payload.system_prompt,
        language=payload.language,
        voice=payload.voice,
    )
    return VoiceSessionResponse(**result)


@router.websocket("/voice/stream")
async def voice_stream(websocket: WebSocket) -> None:
    """One voice turn: send a config message, then text or raw PCM16 audio; receive the transcript, Gemini's reply
    as text, and the reply spoken sentence by sentence (binary MP3 frames).

    The full protocol is documented in app/voice/protocol.py and in the README. It composes the existing STT, chat
    and TTS services; `/stt/stream`, `/chat`, `/chat/stream` and `/tts/stream` are unchanged.
    """
    service: VoiceStreamService = websocket.app.state.voice_service
    await service.run(websocket, request_id=uuid.uuid4().hex[:16])
