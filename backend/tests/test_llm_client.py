import asyncio
import json

import httpx
import pytest

from app.common.logging import redact_llm_keys
from app.llm.client import LLMClient, LLMError
from app.llm.providers import PROVIDERS


def _ok(content="hi"):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _recorder(status=200, content="hi"):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": "nope"})
        return _ok(content)

    return seen, httpx.MockTransport(handler)


async def test_sends_bearer_key_and_model():
    seen, tr = _recorder()
    c = LLMClient("groq", "k1", transport=tr)
    assert await c.generate("p") == "hi"
    r = seen[0]
    assert str(r.url).endswith("/chat/completions")
    assert r.headers["authorization"] == "Bearer k1"
    assert json.loads(r.content)["model"] == PROVIDERS["groq"].default_model


async def test_two_clients_do_not_share_keys():
    seen1, t1 = _recorder()
    seen2, t2 = _recorder()
    a = LLMClient("groq", "k1", transport=t1)
    b = LLMClient("groq", "k2", transport=t2)
    await asyncio.gather(a.generate("x"), b.generate("y"))
    assert seen1[0].headers["authorization"] == "Bearer k1"
    assert seen2[0].headers["authorization"] == "Bearer k2"


async def test_generate_json_parses_fenced_json():
    _, tr = _recorder(content='```json\n{"a":1}\n```')
    c = LLMClient("groq", "k1", transport=tr)
    assert await c.generate_json("p", schema={"type": "object"}) == {"a": 1}


async def test_json_schema_only_when_supported():
    seen, tr = _recorder(content="{}")
    await LLMClient("gemini", "k", transport=tr).generate_json("p", schema={"type": "object"})
    assert json.loads(seen[0].content)["response_format"]["type"] == "json_schema"
    seen2, tr2 = _recorder(content="{}")
    await LLMClient("groq", "k", transport=tr2).generate_json("p", schema={"type": "object"})
    assert json.loads(seen2[0].content)["response_format"]["type"] == "json_object"


async def test_401_maps_to_key_invalid_without_leaking_key():
    _, tr = _recorder(status=401)
    c = LLMClient("groq", "k1", transport=tr)
    with pytest.raises(LLMError) as ei:
        await c.generate("p")
    assert ei.value.code == "llm_key_invalid"
    assert "k1" not in str(ei.value)


async def test_429_maps_to_rate_limited(monkeypatch):
    import app.llm.client as mod

    monkeypatch.setattr(mod, "_RETRY_WAIT", lambda *_a, **_k: 0)
    _, tr = _recorder(status=429)
    c = LLMClient("groq", "k1", transport=tr)
    with pytest.raises(LLMError) as ei:
        await c.generate("p")
    assert ei.value.code == "llm_rate_limited"
    assert "k1" not in str(ei.value)


def test_redaction_processor_hides_llm_key():
    out = redact_llm_keys(None, "info", {"x-llm-key": "k1", "api_key": "k1", "ok": "v"})
    assert out["x-llm-key"] == "***"
    assert out["api_key"] == "***"
    assert out["ok"] == "v"
