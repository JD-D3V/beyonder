from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import sessions
from app.auth.passwords import hash_password
from app.main import app
from app.scripts.create_admin import create_admin
from app.storage.models import Invite, User, UserSession

pytestmark = pytest.mark.db


@pytest.fixture
def client(db_session):
    with TestClient(app) as c:
        yield c


def _admin_token(client, db_session):
    create_admin(db_session, "owner@example.com", "owner-password")
    db_session.commit()
    r = client.post(
        "/auth/login", json={"email": "owner@example.com", "password": "owner-password"}
    )
    assert r.status_code == 200
    return r.json()["token"]


def _invite(client, tok, days=7):
    r = client.post(
        "/admin/invites", json={"days": days}, headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 200
    return r.json()["code"]


def _signup(client, code, email="new@example.com"):
    return client.post(
        "/auth/signup", json={"email": email, "password": "password123", "invite": code}
    )


def test_signup_requires_unused_unexpired_invite(client, db_session):
    tok = _admin_token(client, db_session)
    assert _signup(client, "nope").status_code == 400
    code = _invite(client, tok)
    ok = _signup(client, code)
    assert ok.status_code == 200 and ok.json()["token"]
    expired = Invite(
        code="old",
        created_by=db_session.query(User).first().id,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(expired)
    db_session.commit()
    assert _signup(client, "old", "other@example.com").status_code == 400


def test_invite_single_use(client, db_session):
    tok = _admin_token(client, db_session)
    code = _invite(client, tok)
    assert _signup(client, code, "a@example.com").status_code == 200
    assert _signup(client, code, "b@example.com").status_code == 400


def test_expired_session_is_401(client, db_session):
    tok = _admin_token(client, db_session)
    row = db_session.query(UserSession).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


def test_logout_revokes(client, db_session):
    tok = _admin_token(client, db_session)
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/auth/me", headers=h).status_code == 200
    assert client.post("/auth/logout", headers=h).status_code == 200
    assert client.get("/auth/me", headers=h).status_code == 401


def test_create_admin_refuses_second_admin(db_session):
    create_admin(db_session, "owner@example.com", "owner-password")
    with pytest.raises(SystemExit):
        create_admin(db_session, "second@example.com", "another-password")
    with pytest.raises(SystemExit):
        create_admin(db_session, "", "x")


def test_email_case_insensitive_login(client, db_session):
    db_session.add(User(email="mixed@example.com", password_hash=hash_password("password123")))
    db_session.commit()
    r = client.post(
        "/auth/login", json={"email": "  MiXeD@Example.COM ", "password": "password123"}
    )
    assert r.status_code == 200
    bad_pw = client.post(
        "/auth/login", json={"email": "mixed@example.com", "password": "wrongwrong"}
    )
    unknown = client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "wrongwrong"}
    )
    assert bad_pw.status_code == unknown.status_code == 401
    assert bad_pw.json() == unknown.json()
