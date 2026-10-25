from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """The documented /health contract.

    The Backend's VoiceAgentClient only requires a 2xx status and (optionally) a JSON object, so the extra
    fields below are for humans and monitoring. Provider readiness (LLM/STT/TTS) is added in later phases.
    """

    status: str
    service: str
    version: str
    environment: str


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Liveness: the process is up and able to answer. Deliberately checks no external dependency."""
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version=settings.service_version,
        environment=settings.environment,
    )
