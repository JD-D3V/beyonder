"""Accounts: login, invite-only signup, logout, and admin invite management."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..auth import sessions
from ..auth.deps import bearer_token, current_user, require_admin
from ..auth.passwords import hash_password, verify_password
from ..storage.db import get_session
from ..storage.models import Invite, User

router = APIRouter()

MIN_PASSWORD = 8
_BAD_LOGIN = "Incorrect email or password."
# Verified against when the email is unknown so both failures cost the same.
_DUMMY_HASH = hash_password("timing-equalizer")


def norm_email(email: str) -> str:
    return email.strip().lower()


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class SignupIn(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=MIN_PASSWORD, max_length=1024)
    invite: str = Field(min_length=1, max_length=128)


class InviteIn(BaseModel):
    days: int = Field(default=7, ge=1, le=90)


def _user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "is_admin": u.is_admin}


@router.post("/auth/login")
async def login(body: LoginIn) -> dict:
    with get_session() as s:
        user = s.execute(
            select(User).where(User.email == norm_email(body.email))
        ).scalar_one_or_none()
        ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
        if user is None or not ok:
            raise HTTPException(status_code=401, detail=_BAD_LOGIN)
        return {"token": sessions.create_session(s, user), "user": _user_out(user)}


@router.post("/auth/signup")
async def signup(body: SignupIn) -> dict:
    email = norm_email(body.email)
    now = datetime.now(timezone.utc)
    invalid = HTTPException(status_code=400, detail="Invalid or expired invite.")
    with get_session() as s:
        inv = s.get(Invite, body.invite)
        if inv is None or inv.used_by is not None or inv.expires_at <= now:
            raise invalid
        user = User(email=email, password_hash=hash_password(body.password))
        s.add(user)
        try:
            s.flush()
        except IntegrityError:
            s.rollback()
            raise HTTPException(status_code=409, detail="That email is already registered.")
        # Atomic claim: of two concurrent signups on one code only one updates a row.
        claimed = s.execute(
            update(Invite)
            .where(
                Invite.code == body.invite,
                Invite.used_by.is_(None),
                Invite.expires_at > now,
            )
            .values(used_by=user.id)
        )
        if claimed.rowcount != 1:
            s.rollback()
            raise invalid
        return {"token": sessions.create_session(s, user), "user": _user_out(user)}


@router.post("/auth/logout")
async def logout(request: Request, _user: User = Depends(current_user)) -> dict:
    with get_session() as s:
        sessions.revoke(s, bearer_token(request))
    return {"ok": True}


@router.get("/auth/me")
async def me(user: User = Depends(current_user)) -> dict:
    return _user_out(user)


@router.post("/admin/invites")
async def create_invite(body: InviteIn | None = None, admin: User = Depends(require_admin)) -> dict:
    days = (body or InviteIn()).days
    code = secrets.token_urlsafe(16)
    with get_session() as s:
        s.add(
            Invite(
                code=code,
                created_by=admin.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=days),
            )
        )
    return {"code": code}


@router.get("/admin/invites")
async def list_invites(_admin: User = Depends(require_admin)) -> list[dict]:
    with get_session() as s:
        rows = s.execute(select(Invite).order_by(Invite.expires_at.desc())).scalars().all()
        return [
            {
                "code": i.code,
                "used": i.used_by is not None,
                "expires_at": i.expires_at.isoformat(),
            }
            for i in rows
        ]
