from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import BCRYPT_MAX_BYTES

MIN_PASSWORD_LENGTH = 8


def _normalize_email(value: str) -> str:
    return value.strip().lower()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)

    @field_validator("email", mode="after")
    @classmethod
    def lowercase_email(cls, value: str) -> str:
        return _normalize_email(value)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
            raise ValueError(f"Password must be at most {BCRYPT_MAX_BYTES} bytes long")
        return value

    @field_validator("full_name")
    @classmethod
    def blank_name_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None


class LoginRequest(BaseModel):
    # Deliberately lenient: login should answer "invalid credentials", not describe password rules.
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="after")
    @classmethod
    def lowercase_email(cls, value: str) -> str:
        return _normalize_email(value)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
