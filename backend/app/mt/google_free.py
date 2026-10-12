"""Google Translate's unofficial web endpoint (``translate_a/single``).

Free and keyless, but unofficial: it can be rate limited or blocked at any
time, which is why requests go through ``gate`` (throttle, backoff, breaker)
and why ``MT_PROVIDER`` can switch to LibreTranslate or off.
"""
from __future__ import annotations

import time

import httpx

from . import gate
from .chunking import chunk_text
from .provider import MTError

URL = "https://translate.googleapis.com/translate_a/single"
CHUNK_CHARS = 4500
USER_AGENT = "Mozilla/5.0 (compatible; Beyonder/0.1)"

# ``gtx`` is the documented client id; some networks get a captcha 429 for it
# while the Chrome dictionary extension's id still works, so fall through.
CLIENTS = ("gtx", "dict-chrome-ex")
CLIENT_BACKOFF_S = 3600.0
_blocked_until: dict[str, float] = {}

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
            # POST with the text in the body: a GET puts it in the URL, and a
            # chapter-sized chunk of Chinese is far past Google's URL limit (400).
            # A client id that answered 429 is skipped for an hour, so a captcha'd
            # id doesn't cost a wasted request on every chunk.
            now = time.monotonic()
            order = [c for c in CLIENTS if _blocked_until.get(c, 0) <= now] or list(CLIENTS)
            for i, cid in enumerate(order):
                r = await client.post(
                    URL, params={"client": cid, "sl": sl, "tl": tl, "dt": "t"}, data={"q": q}
                )
                if r.status_code == 429:
                    _blocked_until[cid] = time.monotonic() + CLIENT_BACKOFF_S
                    if i < len(order) - 1:
                        continue
                break
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
