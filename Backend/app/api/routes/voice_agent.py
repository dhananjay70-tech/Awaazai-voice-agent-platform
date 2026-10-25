from typing import Literal

from pydantic import BaseModel
from fastapi import APIRouter

from app.api.dependencies import CurrentUser, VoiceAgentDep
from app.core.errors import VoiceAgentTimeoutError, VoiceAgentUnavailableError

router = APIRouter(prefix="/voice-agent", tags=["voice-agent"])


class VoiceAgentStatus(BaseModel):
    configured: bool
    status: Literal["ok", "not_configured", "unavailable", "timeout"]
    detail: str | None = None


@router.get("/status", response_model=VoiceAgentStatus)
async def voice_agent_status(_: CurrentUser, client: VoiceAgentDep) -> VoiceAgentStatus:
    """Report whether the VoiceAgent service is reachable. Always 200; the body carries the result."""
    if not client.configured:
        return VoiceAgentStatus(configured=False, status="not_configured", detail="VOICE_AGENT_BASE_URL is not set")
    try:
        await client.health()
    except VoiceAgentTimeoutError as exc:
        return VoiceAgentStatus(configured=True, status="timeout", detail=exc.message)
    except VoiceAgentUnavailableError as exc:
        return VoiceAgentStatus(configured=True, status="unavailable", detail=exc.message)
    return VoiceAgentStatus(configured=True, status="ok")
