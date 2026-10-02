"""Decide which LLM credentials a request may use.

The server's own key is reachable ONLY by admins who supply no key of their own.
"""
from __future__ import annotations

from typing import Any, Mapping

from fastapi import HTTPException

from ..common.config import settings
from .client import LLMClient
from .providers import PROVIDERS

_NEED_KEY = (
    "Add your own AI API key (provider and key) in Settings to use this feature."
)


def _need_key() -> HTTPException:
    return HTTPException(402, detail={"code": "llm_key_required", "detail": _NEED_KEY})


def resolve_llm(headers: Mapping[str, str], user: Any | None) -> LLMClient:
    h = {k.lower(): v for k, v in headers.items()}
    provider = (h.get("x-llm-provider") or "").strip().lower()
    key = (h.get("x-llm-key") or "").strip()
    model = (h.get("x-llm-model") or "").strip() or None

    if provider and provider not in PROVIDERS:
        raise HTTPException(
            400,
            detail={"code": "llm_provider_unknown", "detail": "Unknown AI provider."},
        )
    if key:
        return LLMClient(provider or "gemini", key, model)
    if (
        user is not None
        and getattr(user, "is_admin", False)
        and provider in ("", "gemini")
        and settings.gemini_api_key
    ):
        return LLMClient("gemini", settings.gemini_api_key, model)
    raise _need_key()
