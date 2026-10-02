"""OpenAI-compatible chat client bound to one provider + one API key.

Security: the key lives only on the instance and in the Authorization header.
It is never put in exception messages or logs.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from ..common.logging import get_logger
from ..common.rate_limit import limiter_for
from .providers import PROVIDERS

log = get_logger(__name__)

_backoff = wait_exponential(multiplier=1, min=2, max=30)


def _RETRY_WAIT(retry_state) -> float:  # indirection so tests can zero the wait
    return _backoff(retry_state)


def _wait(retry_state) -> float:
    return _RETRY_WAIT(retry_state)


class LLMError(RuntimeError):
    """code in {"llm_key_invalid", "llm_rate_limited", "llm_upstream"}."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _retryable(e: BaseException) -> bool:
    return isinstance(e, LLMError) and e.code in ("llm_rate_limited", "llm_upstream")


class LLMClient:
    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider: {provider}")
        self.provider = provider
        self.api_key = api_key
        self._p = PROVIDERS[provider]
        self.model_name = model or self._p.default_model
        self._transport = transport

    def __repr__(self) -> str:  # never expose the key
        return f"LLMClient(provider={self.provider!r}, model={self.model_name!r})"

    @retry(
        retry=retry_if_exception(_retryable),
        wait=_wait,
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _chat(self, body: dict[str, Any]) -> str:
        limiter = limiter_for(_key_id(self.api_key))
        async with limiter:
            try:
                async with httpx.AsyncClient(
                    transport=self._transport, timeout=120.0
                ) as http:
                    resp = await http.post(
                        f"{self._p.base_url}/chat/completions",
                        json=body,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                    )
            except httpx.HTTPError as e:
                raise LLMError(
                    "llm_upstream", f"{self.provider} request failed: {type(e).__name__}"
                ) from None
        s = resp.status_code
        if s in (401, 403):
            raise LLMError("llm_key_invalid", f"{self.provider} rejected the API key ({s})")
        if s == 429:
            raise LLMError("llm_rate_limited", f"{self.provider} rate limited the request (429)")
        if s >= 400:
            raise LLMError("llm_upstream", f"{self.provider} returned HTTP {s}")
        try:
            text = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            raise LLMError("llm_upstream", f"{self.provider} returned a malformed response") from None
        if not text:
            raise LLMError("llm_upstream", f"{self.provider} returned an empty response")
        return text

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 4096,
        _response_format: dict | None = None,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_output_tokens,
        }
        if _response_format:
            body["response_format"] = _response_format
        return await self._chat(body)

    async def generate_json(
        self,
        prompt: str,
        *,
        schema: dict,
        system: str | None = None,
        temperature: float = 0.1,
        max_output_tokens: int = 4096,
    ) -> Any:
        if self._p.supports_json_schema:
            rf: dict = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": schema},
            }
        else:
            rf = {"type": "json_object"}
            hint = "Respond with a single JSON object matching this schema:\n" + json.dumps(schema)
            system = f"{system}\n\n{hint}" if system else hint
        raw = await self.generate(
            prompt,
            system=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            _response_format=rf,
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            cleaned = raw.strip().lstrip("`").rstrip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            return json.loads(cleaned)


def _key_id(api_key: str) -> str:
    import hashlib

    return hashlib.sha256(api_key.encode()).hexdigest()[:16]
