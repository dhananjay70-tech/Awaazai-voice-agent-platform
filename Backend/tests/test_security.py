from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.errors import AuthConfigError, InvalidTokenError
from app.core.security import (
    JWT_ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from tests.conftest import TEST_JWT_SECRET, make_settings


def test_password_is_hashed_and_verifiable():
    hashed = hash_password("my-password-1")
    assert hashed != "my-password-1"
    assert "my-password-1" not in hashed
    assert verify_password("my-password-1", hashed)
    assert not verify_password("wrong-password", hashed)


def test_hashes_are_salted():
    assert hash_password("same-password") != hash_password("same-password")


def test_verify_password_with_garbage_hash_is_false():
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_token_round_trip(settings):
    token, expires_in = create_access_token("user-123", settings)
    assert expires_in == settings.access_token_expire_minutes * 60
    assert decode_access_token(token, settings) == "user-123"


def test_expired_token_rejected(settings):
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    token = jwt.encode({"sub": "u", "exp": past}, TEST_JWT_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, settings)


def test_token_signed_with_other_secret_rejected(settings):
    other = jwt.encode(
        {"sub": "u", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "x" * 40,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(other, settings)


def test_unsigned_alg_none_token_rejected(settings):
    forged = jwt.encode({"sub": "u", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, None, algorithm="none")
    with pytest.raises(InvalidTokenError):
        decode_access_token(forged, settings)


def test_token_without_expiry_rejected(settings):
    token = jwt.encode({"sub": "u"}, TEST_JWT_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, settings)


def test_garbage_token_rejected(settings):
    with pytest.raises(InvalidTokenError):
        decode_access_token("not.a.jwt", settings)


def test_no_secret_configured_means_no_tokens():
    with pytest.raises(AuthConfigError):
        create_access_token("u", make_settings(jwt_secret=None))
