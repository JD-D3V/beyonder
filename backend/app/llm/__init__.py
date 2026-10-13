"""Per-request, bring-your-own-key LLM client (OpenAI-compatible)."""
from .client import LLMClient, LLMError

__all__ = ["LLMClient", "LLMError"]
