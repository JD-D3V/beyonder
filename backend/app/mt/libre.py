"""Self-hosted LibreTranslate (``LIBRETRANSLATE_URL``)."""
from __future__ import annotations

import httpx

from ..common.config import settings
from . import gate
from .provider import MTError

# Tests inject an httpx.MockTransport here.
_transport: httpx.AsyncBaseTransport | None = None


async def libre_translate(
    base: str, texts: list[str], source: str = "zh",
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[str]:
    """POST one batch to ``{base}/translate``. Raises ``httpx.HTTPError`` or
    ``ValueError`` on failure (the public proxy maps those to a 502)."""
    async with httpx.AsyncClient(timeout=60, transport=transport) as c:
        r = await c.post(
            f"{base.rstrip('/')}/translate",
            json={"q": texts, "source": source, "target": "en", "format": "text"},
        )
    r.raise_for_status()
    out = r.json().get("translatedText")
    if not isinstance(out, list) or len(out) != len(texts):
        raise ValueError("unexpected response shape")
    return [str(t) for t in out]


class LibreProvider:
    name = "libretranslate"

    async def translate(
        self, texts: list[str], source: str = "zh-CN", target: str = "en"
    ) -> list[str]:
        base = settings.libretranslate_url
        src = source.split("-")[0].lower()
        out: list[str] = []
        for text in texts:
            if not text.strip():
                out.append(text)
                continue

            async def fn(t: str = text) -> list[str]:
                try:
                    return await libre_translate(base, [t], src, _transport)
                except ValueError as e:
                    raise MTError(str(e)) from e

            out.append((await gate.call(fn))[0])
        return out
