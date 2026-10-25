"""Application settings, loaded from environment variables (and an optional .env file)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

BACKEND_DIR = Path(__file__).resolve().parents[2]

MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "AwaazAI Backend"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Comma-separated list of allowed browser origins (the Vite dev server by default).
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Database ---
    # Either set DATABASE_URL, or the individual POSTGRES_* values below.
    database_url: SecretStr | None = None
    postgres_host: str | None = None
    postgres_port: int = 5432
    postgres_user: str | None = None
    postgres_password: SecretStr | None = None
    postgres_db: str | None = None
    db_connect_timeout_seconds: int = 5
    # Connections per worker process = pool_size + max_overflow. Hosted poolers cap total clients
    # (e.g. Supabase session mode: 15 for the whole project), so keep this small and multiply by workers.
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)

    # --- Authentication ---
    # No default on purpose: a hardcoded secret would be a vulnerability.
    jwt_secret: SecretStr | None = None
    access_token_expire_minutes: int = 30

    # --- Rate limiting (stored in PostgreSQL, so it is shared by all workers/instances) ---
    rate_limit_enabled: bool = True
    # Number of trusted reverse proxies in front of the app. 0 = ignore X-Forwarded-For completely.
    # Set to N only when the app is reachable exclusively through exactly N proxies you control.
    trusted_proxy_count: int = Field(default=0, ge=0, le=10)
    rate_limit_register_max: int = Field(default=10, ge=1)
    rate_limit_register_window_seconds: int = Field(default=3600, ge=1, le=86_400)
    rate_limit_login_ip_max: int = Field(default=20, ge=1)
    rate_limit_login_ip_window_seconds: int = Field(default=300, ge=1, le=86_400)
    rate_limit_login_email_max: int = Field(default=10, ge=1)
    rate_limit_login_email_window_seconds: int = Field(default=900, ge=1, le=86_400)

    # --- VoiceAgent service ---
    voice_agent_base_url: str | None = None
    voice_agent_timeout_seconds: float = 5.0

    @model_validator(mode="after")
    def _validate_security(self) -> "Settings":
        if self.jwt_secret is not None:
            if len(self.jwt_secret.get_secret_value()) < MIN_JWT_SECRET_LENGTH:
                raise ValueError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters long")
        if self.environment == "production":
            if self.jwt_secret is None:
                raise ValueError("JWT_SECRET is required when ENVIRONMENT=production")
            if "*" in self.cors_origin_list:
                raise ValueError("CORS_ORIGINS must not contain '*' when ENVIRONMENT=production")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def sqlalchemy_database_url(self) -> URL | None:
        """The SQLAlchemy URL (psycopg 3 driver), or None when no database is configured."""
        if self.database_url is not None:
            raw = self.database_url.get_secret_value().strip()
            for prefix in ("postgresql://", "postgres://"):
                if raw.startswith(prefix):
                    raw = "postgresql+psycopg://" + raw[len(prefix):]
            return make_url(raw)
        if self.postgres_host and self.postgres_user and self.postgres_db:
            return URL.create(
                drivername="postgresql+psycopg",
                username=self.postgres_user,
                password=self.postgres_password.get_secret_value() if self.postgres_password else None,
                host=self.postgres_host,
                port=self.postgres_port,
                database=self.postgres_db,
            )
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
