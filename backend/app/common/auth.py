"""Shared-secret gate for the whole API.

The deployed frontend is a static site on a public host, so it cannot keep a
secret: anything compiled into the bundle is readable by anyone who opens the
page. The token is therefore entered once in the browser and kept in that
browser's local storage, never committed and never built into the export.

Set API_TOKEN to turn this on. Leave it empty and the API is open, which is
what local development wants.

Two paths stay open on purpose:

* ``OPTIONS``, because a CORS preflight is sent by the browser before it is
  allowed to attach any custom header. Rejecting it would block every
  cross-origin request, token or not.
* ``/health``, because the platform healthcheck cannot carry credentials, and
  it reveals only that the process is up.
"""
from __future__ import annotations

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .logging import get_logger

log = get_logger(__name__)

_OPEN_PATHS = frozenset({"/health"})

_HEADER = "x-api-token"


def _presented_token(request: Request) -> str:
    header = request.headers.get(_HEADER)
    if header:
        return header.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        expected = settings.api_token
        if not expected:
            return await call_next(request)
        if request.method == "OPTIONS" or request.url.path in _OPEN_PATHS:
            return await call_next(request)

        presented = _presented_token(request)
        # compare_digest keeps the comparison time independent of how much of
        # the token matched.
        if not presented or not secrets.compare_digest(presented, expected):
            log.warning(
                "auth.rejected",
                path=request.url.path,
                method=request.method,
                had_token=bool(presented),
            )
            return JSONResponse(
                status_code=401,
                content={
                    "detail": (
                        "This library is private. Send the access token in the "
                        "X-API-Token header."
                    )
                },
            )
        return await call_next(request)
