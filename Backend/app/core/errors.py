"""Application errors and the handlers that turn every failure into one JSON shape:

    {"error": {"code": "...", "message": "...", "details": ..., "request_id": "..."}}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.security_headers import apply_security_headers

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors that should become a clean API response."""

    status_code = 500
    code = "internal_error"
    message = "Internal server error"

    headers: dict[str, str] | None = None

    def __init__(self, message: str | None = None, details: Any = None) -> None:
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "invalid_credentials"
    message = "Invalid email or password"  # deliberately does not say which one was wrong


class InvalidTokenError(AppError):
    status_code = 401
    code = "invalid_token"
    message = "Could not validate credentials"


class EmailAlreadyRegisteredError(AppError):
    status_code = 409
    code = "email_already_registered"
    message = "An account with this email already exists"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Resource not found"


class AgentNameConflictError(AppError):
    status_code = 409
    code = "agent_name_conflict"
    message = "You already have an agent with this name"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Please try again later."

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(details={"retry_after_seconds": retry_after_seconds})
        self.headers = {"Retry-After": str(retry_after_seconds)}


class DatabaseUnavailableError(AppError):
    status_code = 503
    code = "database_unavailable"
    message = "The database is not available"


class AuthConfigError(AppError):
    status_code = 503
    code = "auth_not_configured"
    message = "Authentication is not configured on this server"


class VoiceAgentUnavailableError(AppError):
    status_code = 503
    code = "voice_agent_unavailable"
    message = "The VoiceAgent service is not available"


class VoiceAgentTimeoutError(AppError):
    status_code = 504
    code = "voice_agent_timeout"
    message = "The VoiceAgent service did not respond in time"


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": getattr(request.state, "request_id", None),
    }
    if details is not None:
        body["details"] = details
    return JSONResponse({"error": body}, status_code=status_code, headers=headers)


def _find_database_error(exc: BaseException) -> SQLAlchemyError | None:
    """Find a SQLAlchemy error in an exception's cause/context chain (it may have been wrapped)."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, SQLAlchemyError):
            return exc
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return None


def _log_database_error(request: Request, exc: SQLAlchemyError) -> None:
    """Log only the error types. str(exc) contains the SQL statement, which can embed user data."""
    driver_error = getattr(exc, "orig", None)
    logger.error(
        "Database error on %s %s [%s]: %s (driver: %s)",
        request.method,
        request.url.path,
        getattr(request.state, "request_id", None),
        exc.__class__.__name__,
        driver_error.__class__.__name__ if driver_error is not None else "n/a",
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        headers = dict(exc.headers or {})
        if exc.status_code == 401:
            headers["WWW-Authenticate"] = "Bearer"
        return _error_response(request, exc.status_code, exc.code, exc.message, exc.details, headers or None)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Only field locations and messages are returned; submitted values (e.g. passwords) are not echoed.
        details = [
            {"field": ".".join(str(part) for part in err["loc"] if part != "body"), "message": err["msg"]}
            for err in exc.errors()
        ]
        return _error_response(request, 422, "validation_error", "Request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(request, exc.status_code, f"http_{exc.status_code}", str(exc.detail), headers=exc.headers)

    @app.exception_handler(OperationalError)
    async def handle_db_operational_error(request: Request, exc: OperationalError) -> JSONResponse:
        logger.error("Database operational error: %s", exc.__class__.__name__)
        err = DatabaseUnavailableError()
        return _error_response(request, err.status_code, err.code, err.message)

    @app.exception_handler(SQLAlchemyError)
    async def handle_db_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        _log_database_error(request, exc)
        return _error_response(request, 500, "internal_error", "Internal server error")

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Unhandled errors are answered by Starlette's outermost layer, which bypasses our middleware,
        # so the request id and security headers must be added here.
        request_id = getattr(request.state, "request_id", None)
        db_error = _find_database_error(exc)
        if db_error is not None:
            _log_database_error(request, db_error)
        else:
            logger.exception("Unhandled error on %s %s [%s]", request.method, request.url.path, request_id)
        response = _error_response(request, 500, "internal_error", "Internal server error")
        apply_security_headers(response, request, request.app.state.settings)
        return response
