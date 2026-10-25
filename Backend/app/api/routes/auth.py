from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import ClientIpDep, DbDep, RateLimiterDep, SettingsDep
from app.core.errors import EmailAlreadyRegisteredError, InvalidCredentialsError
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.user import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbDep, limiter: RateLimiterDep, client_ip: ClientIpDep) -> User:
    limiter.check_register(client_ip)
    if db.scalar(select(User.id).where(User.email == payload.email)) is not None:
        raise EmailAlreadyRegisteredError()

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:  # two simultaneous registrations: the unique constraint wins
        db.rollback()
        raise EmailAlreadyRegisteredError() from exc
    return user


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest, db: DbDep, settings: SettingsDep, limiter: RateLimiterDep, client_ip: ClientIpDep
) -> TokenResponse:
    limiter.check_login(client_ip, payload.email)  # counts every attempt, so a correct guess is not exempt
    user = db.scalar(select(User).where(User.email == payload.email))
    # Always run one bcrypt check so unknown emails take as long as wrong passwords.
    password_ok = verify_password(payload.password, user.hashed_password if user else DUMMY_PASSWORD_HASH)
    if user is None or not password_ok or not user.is_active:
        raise InvalidCredentialsError()

    token, expires_in = create_access_token(str(user.id), settings)
    return TokenResponse(access_token=token, expires_in=expires_in)
