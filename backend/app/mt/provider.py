"""Machine-translation provider interface and the ``MT_PROVIDER`` switch."""
from __future__ import annotations

from typing import Protocol

from ..common.config import settings


class MTError(Exception):
    """A translation request failed (network, bad response)."""


class MTBlocked(MTError):
    """The provider is rate limiting or blocking us; back off for a long while."""


class Provider(Protocol):
    name: str

    async def translate(
        self, texts: list[str], source: str = "zh-CN", target: str = "en"
    ) -> list[str]:
        """One output per input text, same order. Raises ``MTError``."""
        ...


def provider_name() -> str:
    return (settings.mt_provider or "off").strip().lower()


def get_provider() -> Provider | None:
    """The configured provider, or None when MT is off or unconfigured."""
    name = provider_name()
    if name == "google_free":
        from .google_free import GoogleFreeProvider

        return GoogleFreeProvider()
    if name == "libretranslate":
        from .libre import LibreProvider

        if not settings.libretranslate_url:
            return None
        return LibreProvider()
    return None
