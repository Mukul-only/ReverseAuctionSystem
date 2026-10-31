"""FastAPI application entry point.

In development the React app is served by Vite, which proxies /api and /ws to
this process. In the built/demo layout FastAPI serves frontend/dist at "/" so
cookies, CSP, and CSRF behave exactly as they would in production (same
origin).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .config import get_settings
from .db import init_db

settings = get_settings()

# backend/app/main.py -> repo root -> frontend/dist
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline response headers.

    CSP is applied when the backend serves the built SPA. During Vite dev the
    page comes from the dev server, so this CSP never reaches it.
    """

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if not settings.debug:
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; "
                "img-src 'self' data:; "
                "font-src 'self'; "
                "style-src 'self'; "
                "script-src 'self'; "
                "connect-src 'self' ws: wss:; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'",
            )
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"],
)


@app.get("/api/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness probe used by the frontend status card and smoke tests."""
    return {"status": "ok", "service": settings.app_name, "env": settings.env}


# Serve the built SPA when it exists. Assets get their own mount; every other
# non-API path falls back to index.html so client-side routes survive a reload.
if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    resolved_dist = FRONTEND_DIST.resolve()

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def serve_spa(full_path: str) -> FileResponse:
        if full_path.startswith(("api/", "ws/")):
            raise HTTPException(status_code=404)

        candidate = (resolved_dist / full_path).resolve()
        if candidate.is_file() and resolved_dist in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(resolved_dist / "index.html")