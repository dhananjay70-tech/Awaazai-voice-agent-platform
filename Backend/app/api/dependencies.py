"""FastAPI dependencies shared by the route modules."""

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.client_ip import resolve_client_ip
from app.core.config import Settings
from app.core.errors import InvalidTokenError
from app.core.security import decode_access_token
from app.db.session import Database
from app.models.user import User
from app.services.rate_limiter import RateLimiter
from app.services.voice_agent_client import VoiceAgentClient

bearer_scheme = HTTPBearer(auto_error=False)  # auto_error=False so we return our own error shape


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    database: Database = request.app.state.database
    yield from database.session()


def get_voice_agent_client(request: Request) -> VoiceAgentClient:
    return request.app.state.voice_agent_client


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def get_client_ip(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> str:
    peer = request.client.host if request.client else None
    return resolve_client_ip(peer, request.headers.get("x-forwarded-for"), settings.trusted_proxy_count)


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]
VoiceAgentDep = Annotated[VoiceAgentClient, Depends(get_voice_agent_client)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
ClientIpDep = Annotated[str, Depends(get_client_ip)]


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbDep,
    settings: SettingsDep,
) -> User:
    """Protected-route dependency: resolve the user from the Bearer token."""
    if credentials is None:
        raise InvalidTokenError("Not authenticated")
    subject = decode_access_token(credentials.credentials, settings)
    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise InvalidTokenError() from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
