"""Password hashing (bcrypt) and JWT access tokens (PyJWT, HS256 only)."""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import Settings
from app.core.errors import AuthConfigError, InvalidTokenError

JWT_ALGORITHM = "HS256"  # fixed on purpose; never accept the algorithm from the token header
BCRYPT_MAX_BYTES = 72  # bcrypt ignores (or rejects) anything longer


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:  # malformed hash or over-long password
        return False


# A real hash of a random value, used to burn the same CPU time when an email is unknown,
# so response time does not reveal which emails are registered.
DUMMY_PASSWORD_HASH = hash_password("not-a-real-password")


def _secret(settings: Settings) -> str:
    if settings.jwt_secret is None:
        raise AuthConfigError()
    return settings.jwt_secret.get_secret_value()


def create_access_token(subject: str, settings: Settings) -> tuple[str, int]:
    """Return (token, lifetime in seconds)."""
    lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(timezone.utc)
    claims = {"sub": subject, "iat": now, "exp": now + lifetime}
    token = jwt.encode(claims, _secret(settings), algorithm=JWT_ALGORITHM)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str, settings: Settings) -> str:
    """Return the user id (subject) from a valid token, or raise InvalidTokenError."""
    try:
        claims = jwt.decode(
            token,
            _secret(settings),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError() from exc
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise InvalidTokenError()
    return subject
