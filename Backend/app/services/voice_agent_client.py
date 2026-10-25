"""HTTP client for the separate VoiceAgent service (see ../VoiceAgent).

This is only the integration boundary. The AI engine (STT, LLM, TTS, RAG, LangGraph)
lives in VoiceAgent and is intentionally NOT implemented here, and no AI responses are
ever fabricated when the service is down: callers get VoiceAgentUnavailableError or
VoiceAgentTimeoutError instead.

TODO(VoiceAgent): VoiceAgent has no documented API yet. The only call below, GET /health,
is an ASSUMED liveness endpoint. Add real methods (start session, push agent config, ...)
once the VoiceAgent service defines them.
"""

import logging
from typing import Any

import httpx

from app.core.errors import VoiceAgentTimeoutError, VoiceAgentUnavailableError

logger = logging.getLogger(__name__)

HEALTH_PATH = "/health"  # ASSUMPTION: confirm against the VoiceAgent service when it exists


class VoiceAgentClient:
    def __init__(
        self,
        base_url: str | None,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._timeout = timeout_seconds
        self._transport = transport  # lets tests inject a fake transport instead of real network
        self._client: httpx.AsyncClient | None = None

    @property
    def configured(self) -> bool:
        return self._base_url is not None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url or "",
                timeout=httpx.Timeout(self._timeout),
                transport=self._transport,
            )
        return self._client

    async def health(self) -> dict[str, Any]:
        """Ask the VoiceAgent service if it is alive.

        Raises VoiceAgentUnavailableError (not configured / unreachable / bad status)
        or VoiceAgentTimeoutError.
        """
        if not self.configured:
            raise VoiceAgentUnavailableError("VoiceAgent service URL is not configured")
        try:
            response = await self._http().get(HEALTH_PATH)
        except httpx.TimeoutException as exc:
            logger.warning("VoiceAgent health check timed out")
            raise VoiceAgentTimeoutError() from exc
        except httpx.HTTPError as exc:
            logger.warning("VoiceAgent health check failed: %s", exc.__class__.__name__)
            raise VoiceAgentUnavailableError() from exc

        if response.status_code >= 400:
            raise VoiceAgentUnavailableError(f"VoiceAgent service returned HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            body = None
        return body if isinstance(body, dict) else {}

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
