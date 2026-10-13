from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.common.config import settings
from app.llm.resolve import resolve_llm


def test_admin_with_non_gemini_provider_and_no_key_gets_402(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "srv")
    admin = SimpleNamespace(is_admin=True)
    with pytest.raises(HTTPException) as e:
        resolve_llm({"X-LLM-Provider": "openrouter"}, admin)
    assert e.value.status_code == 402
    assert e.value.detail["code"] == "llm_key_required"
