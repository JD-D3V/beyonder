"""Google Translate's unofficial web endpoint (``translate_a/single``).

Free and keyless, but unofficial: it can be rate limited or blocked at any
time, which is why requests go through ``gate`` (throttle, backoff, breaker)
and why ``MT_PROVIDER`` can switch to LibreTranslate or off.
"""
from __future__ import annotations

import httpx

from . import gate
from .chunking import chunk_text
from .provider import MTError

URL = "https://translate.googleapis.com/translate_a/single"
CHUNK_CHARS = 4500
USER_AGENT = "Mozilla/5.0 (compatible; Beyonder/0.1)"

# Tests inject an httpx.MockTransport here.
_transport: httpx.AsyncBaseTransport | None = None


def parse_segments(payload: object) -> str:
    """Join the ``[0][*][0]`` translated segments of a ``dt=t`` response."""
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        raise MTError("unexpected response shape")
    parts: list[str] = []
    for seg in payload[0]:
        if isinstance(seg, list) and seg and isinstance(seg[0], str):
            parts.append(seg[0])
    return "".join(parts)


class GoogleFreeProvider:
    name = "google_free"

    async def _one(self, client: httpx.AsyncClient, q: str, sl: str, tl: str) -> str:
        async def fn() -> str:
            r = await client.get(
                URL, params={"client": "gtx", "sl": sl, "tl": tl, "dt": "t", "q": q}
            )
            r.raise_for_status()
            try:
                payload = r.json()
            except ValueError as e:  # not JSON (e.g. a captcha page)
                raise MTError("response was not JSON") from e
            return parse_segments(payload)

        return await gate.call(fn)

    async def translate(
        self, texts: list[str], source: str = "zh-CN", target: str = "en"
    ) -> list[str]:
        out: list[str] = []
        async with httpx.AsyncClient(
            timeout=30, headers={"user-agent": USER_AGENT}, transport=_transport
        ) as client:
            for text in texts:
                pieces = [
                    await self._one(client, c, source, target) if c.strip() else c
                    for c in chunk_text(text, CHUNK_CHARS)
                ]
                out.append("".join(pieces))
        return out
