"""Shared plumbing for TTS providers that stream raw audio bytes from an HTTP POST (Deepgram, Sarvam).

Provider error bodies are never read, logged or returned: only the HTTP status decides which safe error is raised.
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.errors import (
    AppError,
    TtsAuthError,
    TtsBadResponseError,
    TtsProviderError,
    TtsRateLimitError,
    TtsTimeoutError,
    TtsUnavailableError,
)

logger = logging.getLogger(__name__)


def error_for_status(status: int) -> AppError:
    if status in (401, 403):
        return TtsAuthError()
    if status in (402, 429):  # 402: out of credits; 429: quota exceeded or too many concurrent requests
        return TtsRateLimitError()
    if status in (408, 504):
        return TtsTimeoutError()
    return TtsProviderError()  # 400/413/422 (our request was refused) and 5xx alike: nothing the client can fix


async def stream_audio(
    client: httpx.AsyncClient,
    url: str,
    *,
    provider: str,
    params: dict[str, Any] | None,
    json_body: dict[str, Any],
    headers: dict[str, str],
) -> AsyncIterator[bytes]:
    """POST `json_body` and yield the response body as it arrives. Closing the iterator closes the connection."""
    try:
        async with client.stream("POST", url, params=params, json=json_body, headers=headers) as response:
            if response.status_code != 200:
                raise error_for_status(response.status_code)
            if not response.headers.get("content-type", "").lower().startswith("audio/"):
                raise TtsBadResponseError()  # e.g. an HTML/JSON error page served with 200
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk
    except httpx.TimeoutException:
        raise TtsTimeoutError() from None
    except httpx.HTTPError as exc:
        # Type only: the message may contain the URL or provider text.
        logger.warning("%s TTS network failure: %s", provider, type(exc).__name__)
        raise TtsUnavailableError() from None
