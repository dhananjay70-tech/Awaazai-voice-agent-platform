"""HTTP security headers and the request id, applied to every response (including errors)."""

from fastapi import Request, Response

# A JSON/streaming API never needs to load scripts, styles, images or be framed.
API_CSP = "default-src 'none'; frame-ancestors 'none'"
DOCS_PATHS = ("/docs", "/redoc")  # Swagger UI / ReDoc need their own scripts, so they get no CSP


def apply_security_headers(response: Response, request: Request, serves_docs: bool = False) -> None:
    headers = response.headers
    headers["X-Content-Type-Options"] = "nosniff"
    headers["X-Frame-Options"] = "DENY"
    headers["Referrer-Policy"] = "no-referrer"
    headers["Cache-Control"] = "no-store"
    if not (serves_docs and request.url.path.startswith(DOCS_PATHS)):
        headers["Content-Security-Policy"] = API_CSP

    request_id = getattr(request.state, "request_id", None)
    if request_id:
        headers["X-Request-ID"] = request_id
