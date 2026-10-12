"""Free machine translation proxy for the reader's "Web" view.

Forwards to a self-hosted LibreTranslate (LIBRETRANSLATE_URL). The browser's
own on-device translator is preferred; this is the fallback for browsers
without one. Public, so it is rate limited per client IP. Nothing is stored.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth.throttle import SlidingWindow
from ..common.config import settings
from .auth_routes import client_ip

router = APIRouter(prefix="/mt")

MAX_TEXTS = 20
MAX_CHARS = 10_000

_requests = SlidingWindow(limit=60, window_s=5 * 60)

# Tests inject an httpx.MockTransport here.
_transport: httpx.AsyncBaseTransport | None = None


def reset_throttles() -> None:
    _requests.clear()


class TranslateIn(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=MAX_TEXTS)
    source: str = "zh"


class TranslateOut(BaseModel):
    texts: list[str]


@router.get("/status")
async def mt_status() -> dict:
    return {"available": bool(settings.libretranslate_url)}


@router.post("/translate", response_model=TranslateOut)
async def mt_translate(body: TranslateIn, request: Request) -> TranslateOut:
    if not body.source.lower().startswith("zh"):
        raise HTTPException(400, "free translation supports Chinese books only")
    base = settings.libretranslate_url.rstrip("/")
    if not base:
        raise HTTPException(404, "server translation is not configured")
    if sum(len(t) for t in body.texts) > MAX_CHARS:
        raise HTTPException(413, f"at most {MAX_CHARS} characters per request")
    if not _requests.hit(client_ip(request)):
        raise HTTPException(
            429, "too many translation requests, try again in a few minutes"
        )
    try:
        async with httpx.AsyncClient(timeout=60, transport=_transport) as c:
            r = await c.post(
                f"{base}/translate",
                json={"q": body.texts, "source": "zh", "target": "en", "format": "text"},
            )
        r.raise_for_status()
        out = r.json().get("translatedText")
        if not isinstance(out, list) or len(out) != len(body.texts):
            raise ValueError("unexpected response shape")
        return TranslateOut(texts=[str(t) for t in out])
    except (httpx.HTTPError, ValueError) as e:
        raise HTTPException(502, "translation service failed") from e
