import uuid

from fastapi import APIRouter, WebSocket

from app.stt.service import SttStreamService

router = APIRouter(tags=["stt"])


@router.websocket("/stt/stream")
async def stt_stream(websocket: WebSocket) -> None:
    """Live speech-to-text. Send a config message, then binary PCM audio frames, then {"type":"end"}.

    Transcript events (ready, partial, final, done, error) come back as JSON text frames. The full protocol is
    documented in app/stt/protocol.py and in the README. This is a separate stream from the text-chat sessions.
    """
    service: SttStreamService = websocket.app.state.stt_service
    await service.run(websocket, request_id=uuid.uuid4().hex[:16])
