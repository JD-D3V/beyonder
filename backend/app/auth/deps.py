"""FastAPI auth dependencies. Token comes from ``Authorization: Bearer``."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from ..storage.db import get_session
from ..storage.models import User
from . import sessions


def bearer_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return value.strip()


def current_user_optional(request: Request) -> User | None:
    token = bearer_token(request)
    if not token:
        return None  # no DB hit for anonymous readers
    with get_session() as s:
        return sessions.user_for_token(s, token)


def current_user(user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Sign in required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only.")
    return user
