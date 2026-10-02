import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from app.auth import passwords, sessions
from app.auth.deps import current_user
from app.main import app


class _FakeUser:
    id = 7
    email = "reader@example.com"
    is_admin = False


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_password_roundtrip():
    h = passwords.hash_password("correct horse")
    assert h != "correct horse"
    assert passwords.verify_password("correct horse", h)


def test_wrong_password_rejected():
    h = passwords.hash_password("correct horse")
    assert not passwords.verify_password("battery staple", h)
    assert not passwords.verify_password("anything", "not-a-hash")


def test_token_hash_is_sha256_hex():
    t = sessions.new_token()
    assert len(t) >= 43
    h = sessions.hash_token(t)
    assert re.fullmatch(r"[0-9a-f]{64}", h)
    assert h == hashlib.sha256(t.encode()).hexdigest()
    assert sessions.new_token() != t


def test_me_without_token_is_401(client):
    assert client.get("/auth/me").status_code == 401


def test_me_with_malformed_header_is_401(client):
    r = client.get("/auth/me", headers={"Authorization": "Basic abc"})
    assert r.status_code == 401


def test_admin_route_as_non_admin_is_403(client):
    app.dependency_overrides[current_user] = lambda: _FakeUser()
    assert client.get("/admin/invites").status_code == 403
    assert client.post("/admin/invites", json={}).status_code == 403


def test_public_health_needs_no_token(client):
    assert client.get("/health").status_code == 200


def test_signup_short_password_is_422(client):
    r = client.post(
        "/auth/signup",
        json={"email": "a@b.co", "password": "short", "invite": "x"},
    )
    assert r.status_code == 422


def test_cors_allows_put_patch_delete(client):
    r = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PUT",
        },
    )
    allowed = r.headers.get("access-control-allow-methods", "")
    for m in ("PUT", "PATCH", "DELETE"):
        assert m in allowed
