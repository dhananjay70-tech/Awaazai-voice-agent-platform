"""Database engine and session management.

The engine is created lazily so the app can start without any database configured.
"""

import logging
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.errors import DatabaseUnavailableError
from app.db.base import SCHEMA

logger = logging.getLogger(__name__)


class Database:
    """Owns the engine and hands out one session per request."""

    def __init__(
        self,
        url: URL | str | None,
        connect_timeout_seconds: int = 5,
        pool_size: int = 5,
        max_overflow: int = 5,
    ) -> None:
        self._url = url
        self._connect_timeout = connect_timeout_seconds
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    @property
    def configured(self) -> bool:
        return self._url is not None

    @property
    def engine(self) -> Engine:
        if self._url is None:
            raise DatabaseUnavailableError("Database is not configured")
        if self._engine is None:
            self._engine = self._create_engine(self._url)
            self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
        return self._engine

    def _create_engine(self, url: URL | str) -> Engine:
        if str(url).startswith("sqlite"):
            # Tests only: one in-memory DB shared across threads. SQLite has no schemas, so drop the prefix.
            return create_engine(
                url,
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
                hide_parameters=True,
                execution_options={"schema_translate_map": {SCHEMA: None}},
            )
        return create_engine(
            url,
            pool_pre_ping=True,
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
            # Keep bound parameters (emails, password hashes, ...) out of SQLAlchemy error messages and logs.
            hide_parameters=True,
            connect_args={"connect_timeout": self._connect_timeout},
        )

    def open_session(self) -> Session:
        """A standalone session the caller must commit/close (for work that must persist on its own)."""
        _ = self.engine  # ensures the factory exists, or raises DatabaseUnavailableError
        assert self._session_factory is not None
        return self._session_factory()

    def session(self) -> Iterator[Session]:
        """Yield a session; roll back on error and always close it. Routes call commit() themselves."""
        _ = self.engine  # ensures the factory exists, or raises DatabaseUnavailableError
        assert self._session_factory is not None
        with self._session_factory() as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise

    def check(self) -> str:
        """Return 'ok', 'not_configured' or 'unavailable' without raising."""
        if not self.configured:
            return "not_configured"
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return "ok"
        except SQLAlchemyError as exc:
            logger.warning("Database readiness check failed: %s", exc.__class__.__name__)
            return "unavailable"

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None
