from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.scripts.create_admin import create_admin
from app.storage.models import Invite, User, UserSession

pytestmark = pytest.mark.db


@pytest.fixture
def client(db_session):
    with TestClient(app) as c:
        yield c


def _login(client):
    return client.post(
        "/auth/login", json={"email": "owner@example.com", "password": "owner-password"}
    )


def test_login_prunes_sessions(client, db_session):
    create_admin(db_session, "owner@example.com", "owner-password")
    db_session.commit()
    user = db_session.query(User).filter_by(email="owner@example.com").one()
    now = datetime.now(timezone.utc)
    db_session.add(UserSession(token_hash="old", user_id=user.id, expires_at=now - timedelta(days=1)))
    for i in range(12):
        db_session.add(
            UserSession(token_hash=f"s{i:02d}", user_id=user.id, expires_at=now + timedelta(days=1 + i))
        )
    db_session.commit()
    assert _login(client).status_code == 200
    db_session.expire_all()
    rows = db_session.query(UserSession).filter_by(user_id=user.id).all()
    assert "old" not in {x.token_hash for x in rows}
    assert len(rows) == 10


def test_deleted_invitee_does_not_free_invite(client, db_session):
    create_admin(db_session, "owner@example.com", "owner-password")
    db_session.commit()
    tok = _login(client).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    code = client.post("/admin/invites", json={"days": 7}, headers=h).json()["code"]

    def signup(email):
        return client.post(
            "/auth/signup", json={"email": email, "password": "password-123", "invite": code}
        )

    assert signup("new@example.com").status_code == 200
    db_session.expire_all()
    assert db_session.get(Invite, code).used_at is not None
    db_session.delete(db_session.query(User).filter_by(email="new@example.com").one())
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(Invite, code).used_by is None
    assert signup("again@example.com").status_code == 400
