from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import SettingsDep

router = APIRouter(tags=["health"])


@router.get("/")
def root(settings: SettingsDep) -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "docs": "/docs",
        "api": settings.api_v1_prefix,
    }


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up. Deliberately checks no dependencies."""
    return {"status": "ok"}


@router.get("/ready")
def ready(request: Request, settings: SettingsDep) -> JSONResponse:
    """Readiness: can this instance actually serve traffic? Returns 503 if not."""
    checks = {
        "database": request.app.state.database.check(),
        "auth": "ok" if settings.jwt_secret is not None else "not_configured",
    }
    is_ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        {"status": "ready" if is_ready else "not_ready", "checks": checks},
        status_code=200 if is_ready else 503,
    )
