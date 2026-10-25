from fastapi import APIRouter, Request

from app.schemas import TtsRequest
from app.tts.response import AudioStreamResponse
from app.tts.service import TtsService

router = APIRouter(tags=["tts"])


@router.post(
    "/tts/stream",
    response_class=AudioStreamResponse,
    status_code=200,
    responses={
        200: {
            "description": "MP3 audio (`audio/mpeg`), streamed as Deepgram produces it.",
            "content": {"audio/mpeg": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def tts_stream(payload: TtsRequest, request: Request) -> AudioStreamResponse:
    """Speak `text` with Deepgram Aura. The text is synthesized exactly as sent: it is never translated or rewritten.

    Failures before the first audio chunk (missing key, bad voice, quota, busy service...) are JSON errors with an
    HTTP status. A failure after audio started aborts the connection (a truncated download), never a fake success.
    """
    service: TtsService = request.app.state.tts_service
    chunks = service.prepare(text=payload.text, language=payload.language, voice=payload.voice)
    return AudioStreamResponse(chunks, media_type=service.content_type, send_timeout_seconds=service.send_timeout)
