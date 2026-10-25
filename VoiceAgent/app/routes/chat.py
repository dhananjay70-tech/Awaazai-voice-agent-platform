import uuid

from fastapi import APIRouter, Request

from app.chat_service import ChatService
from app.schemas import ChatRequest, ChatResponse
from app.streaming import EventStreamResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Send one user message and get Gemini's complete reply. Conversation context is kept per `session_id`."""
    service: ChatService = request.app.state.chat_service
    session_id = payload.session_id or uuid.uuid4().hex
    reply = await service.chat(message=payload.message, session_id=session_id, language=payload.language)
    return ChatResponse(session_id=session_id, reply=reply, model=service.model)


@router.post(
    "/chat/stream",
    response_class=EventStreamResponse,
    status_code=200,
    responses={
        200: {
            "description": "Server-Sent Events: `start`, many `token`, then `done` (or `error` if generation fails mid-stream).",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def chat_stream(payload: ChatRequest, request: Request) -> EventStreamResponse:
    """Same input and conversation behaviour as `POST /chat`, but the reply arrives progressively as SSE events.

    Failures before the first text chunk exist (missing key, bad key, unknown model, rate limit, busy session...)
    are ordinary JSON errors with an HTTP status, exactly as for `POST /chat`.
    """
    service: ChatService = request.app.state.chat_service
    session_id = payload.session_id or uuid.uuid4().hex
    events = service.stream(
        message=payload.message,
        session_id=session_id,
        language=payload.language,
        request_id=getattr(request.state, "request_id", None),
    )  # an unstarted async generator: it holds nothing until EventStreamResponse starts it (and always closes it)
    return EventStreamResponse(
        events,
        request_id=getattr(request.state, "request_id", None),
        send_timeout_seconds=service.stream_send_timeout,
    )
