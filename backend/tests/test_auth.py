import pytest
from fastapi.testclient import TestClient

from app.common.config import settings
from app.main import app

# /openapi.json is served without touching the database, so it exercises the
# gate rather than the storage layer.
GUARDED = "/openapi.json"
TOKEN = "test-token-value"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def private(monkeypatch):
    monkeypatch.setattr(settings, "api_token", TOKEN)


def test_open_when_no_token_is_configured(client, monkeypatch):
    # Local development should not need a token to get started.
    monkeypatch.setattr(settings, "api_token", "")
    assert client.get(GUARDED).status_code == 200


def test_guarded_path_rejects_missing_token(client, private):
    res = client.get(GUARDED)
    assert res.status_code == 401
    assert "token" in res.json()["detail"].lower()


def test_guarded_path_rejects_wrong_token(client, private):
    res = client.get(GUARDED, headers={"X-API-Token": "not-the-token"})
    assert res.status_code == 401


def test_header_token_is_accepted(client, private):
    assert client.get(GUARDED, headers={"X-API-Token": TOKEN}).status_code == 200


def test_bearer_token_is_accepted(client, private):
    res = client.get(GUARDED, headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200


def test_health_stays_open(client, private):
    # The platform healthcheck cannot carry a credential, and an up/down signal
    # is not worth protecting.
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_preflight_is_not_blocked(client, private):
    # A browser sends OPTIONS before it will attach any custom header, so
    # requiring the token here would break every cross-origin request.
    res = client.options(
        "/novels",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") is not None


def test_rejection_still_carries_cors_headers(client, private):
    # Without these the browser reports an opaque network failure and the page
    # cannot tell the user that the token is wrong.
    res = client.get(
        GUARDED,
        headers={"Origin": "http://localhost:3000", "X-API-Token": "wrong"},
    )
    assert res.status_code == 401
    assert res.headers.get("access-control-allow-origin") is not None
