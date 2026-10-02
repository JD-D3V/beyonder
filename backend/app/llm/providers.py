from __future__ import annotations

from dataclasses import dataclass

from ..common.config import settings


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    default_model: str
    supports_json_schema: bool


PROVIDERS: dict[str, Provider] = {
    p.name: p
    for p in (
        Provider(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            settings.gemini_model,
            True,
        ),
        Provider(
            "openrouter",
            "https://openrouter.ai/api/v1",
            "deepseek/deepseek-chat-v3.1:free",
            False,
        ),
        Provider(
            "groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", False
        ),
        Provider("deepseek", "https://api.deepseek.com/v1", "deepseek-chat", False),
        Provider("openai", "https://api.openai.com/v1", "gpt-4.1-mini", True),
    )
}
