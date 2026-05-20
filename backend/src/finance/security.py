"""Security middleware: rate-limit on /api/auth/login and CSRF (double-submit cookie).

Both are best-effort, in-process safeguards appropriate for a single-user
LAN app. They are not a substitute for the future zero-trust edge.
"""

from __future__ import annotations

import secrets
import time
from collections import deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from finance.config import settings
from finance.auth.sessions import COOKIE_NAME

CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Routes that legitimately have no session cookie yet (and so no CSRF token).
CSRF_EXEMPT_PATHS = {
    "/api/auth/setup",
    "/api/auth/login",
    "/api/auth/needs-setup",
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """5 attempts/min/IP against POST /api/auth/login."""

    def __init__(self, app, max_attempts: int = 5, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}

    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and request.url.path == "/api/auth/login":
            ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            q = self._hits.setdefault(ip, deque())
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_attempts:
                return JSONResponse(
                    {"detail": "Too many login attempts. Try again in a minute."},
                    status_code=429,
                )
            q.append(now)
        return await call_next(request)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie. Enforced only when APP_ENV=production.

    The frontend reads `csrf_token` (non-httponly) and echoes it back as
    `X-CSRF-Token` on every state-changing request.
    """

    async def dispatch(self, request: Request, call_next):
        enforce = settings.app_env == "production"
        is_state_change = request.method not in SAFE_METHODS
        path = request.url.path

        if (
            enforce
            and is_state_change
            and path.startswith("/api/")
            and path not in CSRF_EXEMPT_PATHS
        ):
            cookie = request.cookies.get(CSRF_COOKIE)
            header = request.headers.get(CSRF_HEADER)
            if not cookie or not header or not secrets.compare_digest(cookie, header):
                return JSONResponse(
                    {"detail": "CSRF token missing or mismatched"},
                    status_code=403,
                )

        response: Response = await call_next(request)

        # Ensure an authenticated browser always has a CSRF cookie to echo back.
        if request.cookies.get(COOKIE_NAME) and not request.cookies.get(CSRF_COOKIE):
            response.set_cookie(
                CSRF_COOKIE,
                secrets.token_urlsafe(32),
                max_age=60 * 60 * 24 * 30,
                httponly=False,
                secure=(settings.app_env == "production"),
                samesite="strict",
                path="/",
            )
        return response


def issue_csrf_cookie(response: Response) -> None:
    """Mint a fresh CSRF cookie alongside login/setup."""
    response.set_cookie(
        CSRF_COOKIE,
        secrets.token_urlsafe(32),
        max_age=60 * 60 * 24 * 30,
        httponly=False,
        secure=(settings.app_env == "production"),
        samesite="strict",
        path="/",
    )
