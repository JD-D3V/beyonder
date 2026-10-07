"""Session GC, create_admin conflict and invite used_at (SQLite, no Postgres)."""
import inspect
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.passwords import hash_password
from app.auth.sessions import prune_sessions
from app.scripts.create_admin import create_admin
from app.storage.models import Invite, User, UserSession


def _sqlite_session():
    eng = create_engine("sqlite://")
    for m in (User, UserSession, Invite):
        m.__table__.create(eng)
    return sessionmaker(eng)()


def test_prune_sessions_drops_expired_and_caps_oldest():
    s = _sqlite_session()
    u = User(email="a@x.com", password_hash="h")
    other = User(email="b@x.com", password_hash="h")
    s.add_all([u, other])
    s.flush()
    now = datetime.now(timezone.utc)
    s.add(UserSession(token_hash="expired", user_id=u.id, expires_at=now - timedelta(days=1)))
    s.add(UserSession(token_hash="other", user_id=other.id, expires_at=now - timedelta(days=1)))
    for i in range(12):
        s.add(UserSession(token_hash=f"t{i:02d}", user_id=u.id, expires_at=now + timedelta(days=1 + i)))
    s.flush()
    prune_sessions(s, u.id)
    left = {r.token_hash for r in s.query(UserSession).filter_by(user_id=u.id)}
    assert "expired" not in left
    # 9 newest survive, leaving room for the session about to be created.
    assert left == {f"t{i:02d}" for i in range(3, 12)}
    assert s.get(UserSession, "other") is not None


def test_create_admin_existing_nonadmin_email_exits_cleanly():
    s = _sqlite_session()
    s.add(User(email="u@x.com", password_hash=hash_password("whatever1")))
    s.flush()
    with pytest.raises(SystemExit) as e:
        create_admin(s, "U@x.com", "long-enough-pw")
    assert "u@x.com" in str(e.value) and "non-admin" in str(e.value)


def test_signup_claim_requires_used_at_null():
    import app.api.auth_routes as ar

    src = inspect.getsource(ar.signup)
    assert "Invite.used_at.is_(None)" in src and "used_at=now" in src
