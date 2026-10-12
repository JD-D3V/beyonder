import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import mt
from app.common.config import settings
from app.main import app


@pytest.fixture
def client(monkeypatch):
    mt.reset_throttles()
    monkeypatch.setattr(settings, "libretranslate_url", "http://lt:5000")
    with TestClient(app) as c:
        yield c
    mt.reset_throttles()


def _upstream(monkeypatch, handler):
    monkeypatch.setattr(mt, "_transport", httpx.MockTransport(handler))


def test_status_and_unconfigured(client, monkeypatch):
    assert client.get("/mt/status").json() == {"available": True}
    monkeypatch.setattr(settings, "libretranslate_url", "")
    assert client.get("/mt/status").json() == {"available": False}
    assert client.post("/mt/translate", json={"texts": ["你好"]}).status_code == 404


def test_translate_proxies(client, monkeypatch):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"translatedText": ["Hello", "World"]})

    _upstream(monkeypatch, handler)
    r = client.post("/mt/translate", json={"texts": ["你好", "世界"]})
    assert r.status_code == 200
    assert r.json() == {"texts": ["Hello", "World"]}
    assert seen["url"] == "http://lt:5000/translate"
    assert seen["body"]["source"] == "zh" and seen["body"]["target"] == "en"


def test_limits(client, monkeypatch):
    _upstream(monkeypatch, lambda r: httpx.Response(200, json={"translatedText": ["x"]}))
    assert client.post("/mt/translate", json={"texts": ["a"] * 21}).status_code == 422
    assert client.post("/mt/translate", json={"texts": []}).status_code == 422
    assert client.post("/mt/translate", json={"texts": ["你" * 10_001]}).status_code == 413


def test_upstream_failure_is_502(client, monkeypatch):
    _upstream(monkeypatch, lambda r: httpx.Response(500))
    assert client.post("/mt/translate", json={"texts": ["a"]}).status_code == 502
    _upstream(monkeypatch, lambda r: httpx.Response(200, json={"translatedText": []}))
    assert client.post("/mt/translate", json={"texts": ["a"]}).status_code == 502


def test_rate_limited(client, monkeypatch):
    _upstream(monkeypatch, lambda r: httpx.Response(200, json={"translatedText": ["x"]}))
    codes = [
        client.post("/mt/translate", json={"texts": ["a"]}).status_code for _ in range(61)
    ]
    assert codes[:60] == [200] * 60 and codes[60] == 429
