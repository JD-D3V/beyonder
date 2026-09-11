"""Thin async wrapper around the google-generativeai SDK.

Gemini 2.5 Flash on the free tier: 15 RPM, 1500 RPD, 1M TPM. We share a
process-wide token bucket so concurrent agents never spike past the cap.

Generation uses JSON mode where the schema fits — keeps agent code honest.
"""
from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from typing import Any, Sequence

import google.generativeai as genai
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..common.config import settings
from ..common.logging import get_logger
from ..common.rate_limit import gemini_limiter

log = get_logger(__name__)


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        embed_model: str,
        embed_dim: int,
    ) -> None:
        if not api_key:
            raise GeminiError("GEMINI_API_KEY missing")
        genai.configure(api_key=api_key)
        self.model_name = model
        # The embed endpoint needs the canonical "models/" prefix for models the
        # client library doesn't ship in its base-model list (e.g. the newer
        # gemini-embedding-001); older ones like text-embedding-004 also accept it.
        self.embed_model = (
            embed_model
            if embed_model.startswith(("models/", "tunedModels/"))
            else f"models/{embed_model}"
        )
        self.embed_dim = embed_dim
        self._gen_model = genai.GenerativeModel(model)

    # --- generation ----------------------------------------------------

    @retry(
        retry=retry_if_exception_type(GeminiError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 4096,
        response_mime_type: str | None = None,
        response_schema: dict | None = None,
    ) -> str:
        async with gemini_limiter:
            try:
                cfg: dict[str, Any] = {
                    "temperature": temperature,
                    "max_output_tokens": max_output_tokens,
                }
                if response_mime_type:
                    cfg["response_mime_type"] = response_mime_type
                if response_schema:
                    cfg["response_schema"] = response_schema
                full = prompt if system is None else f"{system}\n\n{prompt}"
                resp = await asyncio.to_thread(
                    self._gen_model.generate_content,
                    full,
                    generation_config=cfg,
                )
                text = (getattr(resp, "text", "") or "").strip()
                if not text:
                    raise GeminiError("empty response")
                return text
            except Exception as e:
                log.warning("gemini.generate_fail", err=str(e))
                raise GeminiError(str(e)) from e

    async def generate_json(
        self,
        prompt: str,
        *,
        schema: dict,
        system: str | None = None,
        temperature: float = 0.1,
        max_output_tokens: int = 4096,
    ) -> Any:
        raw = await self.generate(
            prompt,
            system=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
            response_schema=schema,
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Some models wrap JSON in ```json fences.
            cleaned = raw.strip().lstrip("`").rstrip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            return json.loads(cleaned)

    # --- embeddings ----------------------------------------------------

    @retry(
        retry=retry_if_exception_type(GeminiError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def embed_one(self, text: str, *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
        async with gemini_limiter:
            try:
                resp = await asyncio.to_thread(
                    genai.embed_content,
                    model=self.embed_model,
                    content=text,
                    task_type=task_type,
                    output_dimensionality=self.embed_dim,
                )
                return list(resp["embedding"])
            except Exception as e:
                raise GeminiError(f"embed failed: {e}") from e

    async def embed_many(
        self,
        texts: Sequence[str],
        *,
        task_type: str = "RETRIEVAL_DOCUMENT",
        batch_size: int = 8,
    ) -> list[list[float]]:
        """Batched embed. Sequential by batch to respect RPM cap."""
        out: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            results = await asyncio.gather(
                *[self.embed_one(t, task_type=task_type) for t in chunk]
            )
            out.extend(results)
        return out


@lru_cache(maxsize=1)
def get_gemini() -> GeminiClient:
    return GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        embed_model=settings.gemini_embed_model,
        embed_dim=settings.embedding_dim,
    )
