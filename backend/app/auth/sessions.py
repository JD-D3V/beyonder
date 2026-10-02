"""Opaque bearer sessions. Only the sha256 of a token is stored, so a leaked
database cannot be replayed as live sessions."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..common.config import settings
from ..storage.models import User, UserSession


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(s: Session, user: User) -> str:
    token = new_token()
    s.add(
        UserSession(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.session_days),
        )
    )
    s.flush()
    return token


def user_for_token(s: Session, token: str) -> User | None:
    if not token:
        return None
    row = s.get(UserSession, hash_token(token))
    if row is None:
        return None
    if row.expires_at <= datetime.now(timezone.utc):
        s.delete(row)
        s.flush()
        return None
    return s.get(User, row.user_id)


def revoke(s: Session, token: str) -> None:
    s.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
    s.flush()
