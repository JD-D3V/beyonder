from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.common.config import settings
from app.llm.resolve import resolve_llm

ADMIN = SimpleNamespace(is_admin=True)
USER = SimpleNamespace(is_admin=False)


def test_user_key_header_wins():
    c = resolve_llm(
        {"X-LLM-Provider": "groq", "x-llm-key": "uk", "X-LLM-MODEL": "m1"}, USER
    )
    assert c.provider == "groq" and c.api_key == "uk" and c.model_name == "m1"


def test_admin_without_header_gets_server_key(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "srv")
    c = resolve_llm({}, ADMIN)
    assert c.api_key == "srv" and c.provider == "gemini"


def _code(exc):
    return exc.value.detail["code"]


def test_non_admin_without_key_gets_402_even_if_server_key_set(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "srv")
    with pytest.raises(HTTPException) as e:
        resolve_llm({}, USER)
    assert e.value.status_code == 402 and _code(e) == "llm_key_required"


def test_provider_without_key_gets_402(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "srv")
    with pytest.raises(HTTPException) as e:
        resolve_llm({"X-LLM-Provider": "groq", "X-LLM-Key": ""}, USER)
    assert e.value.status_code == 402


def test_anonymous_gets_402(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "srv")
    with pytest.raises(HTTPException) as e:
        resolve_llm({}, None)
    assert e.value.status_code == 402


def test_unknown_provider_gets_400():
    with pytest.raises(HTTPException) as e:
        resolve_llm({"X-LLM-Provider": "nope", "X-LLM-Key": "k"}, USER)
    assert e.value.status_code == 400 and _code(e) == "llm_provider_unknown"
