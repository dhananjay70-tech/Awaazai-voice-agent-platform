"""HTTP security headers, applied to every response (including errors)."""

from fastapi import Request, Response

from app.core.config import Settings

# This is a JSON API: it never needs to load scripts, styles, images or be framed.
API_CSP = "default-src 'none'; frame-ancestors 'none'"
DOCS_PATHS = ("/docs", "/redoc")  # Swagger UI / ReDoc load their own scripts and styles, so they get no CSP


def apply_security_headers(response: Response, request: Request, settings: Settings) -> None:
    path = request.url.path
    headers = response.headers
    headers["X-Content-Type-Options"] = "nosniff"
    headers["X-Frame-Options"] = "DENY"
    headers["Referrer-Policy"] = "no-referrer"
    headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

    serves_docs = not settings.is_production and path.startswith(DOCS_PATHS)
    if not serves_docs:
        headers["Content-Security-Policy"] = API_CSP

    # Tokens and per-user data must never be stored by browsers or shared caches.
    if path.startswith(settings.api_v1_prefix):
        headers["Cache-Control"] = "no-store"

    # Only meaningful over HTTPS (browsers ignore it on HTTP), so enable it where HTTPS is expected.
    if settings.is_production:
        headers["Strict-Transport-Security"] = "max-age=31536000"

    request_id = getattr(request.state, "request_id", None)
    if request_id:
        headers["X-Request-ID"] = request_id
