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


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_display_name_signup_patch_and_social(client, db_session):
    from app.storage.models import Novel

    tok = _admin_token(client, db_session)
    r = client.post(
        "/auth/signup",
        json={"email": "carol@example.com", "password": "password-1",
              "invite": _invite(client, tok), "display_name": "Carol_9"},
    )
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "Carol_9"
    ctok = r.json()["token"]

    # duplicate (case-insensitive) at signup, and invalid names
    dup = client.post(
        "/auth/signup",
        json={"email": "dave@example.com", "password": "password-1",
              "invite": _invite(client, tok), "display_name": "carol_9"},
    )
    assert dup.status_code == 409
    for bad in ("ab", "x" * 25, "has space", "a@b.c", "reader-7"):
        assert client.patch(
            "/auth/me", json={"display_name": bad}, headers=_hdr(ctok)
        ).status_code == 422

    # signed out
    assert client.patch("/auth/me", json={"display_name": "zed"}).status_code == 401

    # second user without a name: PATCH conflict then success
    r2 = client.post(
        "/auth/signup",
        json={"email": "erin@example.com", "password": "password-1",
              "invite": _invite(client, tok)},
    )
    assert r2.json()["user"]["display_name"] is None
    etok, eid = r2.json()["token"], r2.json()["user"]["id"]
    assert client.patch(
        "/auth/me", json={"display_name": "CAROL_9"}, headers=_hdr(etok)
    ).status_code == 409
    ok = client.patch("/auth/me", json={"display_name": "erin-r"}, headers=_hdr(etok))
    assert ok.status_code == 200 and ok.json()["display_name"] == "erin-r"
    assert client.get("/auth/me", headers=_hdr(etok)).json()["display_name"] == "erin-r"

    # social routes: chosen name, else reader-<id>; never the email
    n = Novel(title="n", source_lang="zh")
    db_session.add(n)
    db_session.commit()
    client.put(f"/novels/{n.id}/review", json={"rating": 4}, headers=_hdr(ctok))
    client.put(f"/novels/{n.id}/review", json={"rating": 5}, headers=_hdr(etok))
    assert client.patch(
        "/auth/me", json={"display_name": None}, headers=_hdr(etok)
    ).json()["display_name"] is None
    authors = {x["author"] for x in client.get(f"/novels/{n.id}/reviews").json()}
    assert authors == {"Carol_9", f"reader-{eid}"}
    assert "example.com" not in str(client.get(f"/novels/{n.id}/reviews").json())
