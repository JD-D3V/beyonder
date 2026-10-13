"""Token-bucket rate limiter for Gemini's 15 RPM free tier.

Single global instance per process. Async-safe.
"""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass

from .config import settings


@dataclass
class _Bucket:
    capacity: int
    refill_per_sec: float
    tokens: float
    last: float


class AsyncRateLimiter:
    def __init__(self, rpm: int, concurrency: int) -> None:
        self._bucket = _Bucket(
            capacity=rpm,
            refill_per_sec=rpm / 60.0,
            tokens=float(rpm),
            last=time.monotonic(),
        )
        self._lock = asyncio.Lock()
        self._sema = asyncio.Semaphore(concurrency)

    async def acquire(self) -> None:
        await self._sema.acquire()
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._bucket.last
                self._bucket.tokens = min(
                    self._bucket.capacity,
                    self._bucket.tokens + elapsed * self._bucket.refill_per_sec,
                )
                self._bucket.last = now
                if self._bucket.tokens >= 1.0:
                    self._bucket.tokens -= 1.0
                    return
                wait = (1.0 - self._bucket.tokens) / self._bucket.refill_per_sec
            await asyncio.sleep(min(wait, 5.0))

    def release(self) -> None:
        self._sema.release()

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.release()


gemini_limiter = AsyncRateLimiter(
    rpm=settings.gemini_rpm_limit,
    concurrency=settings.gemini_concurrency,
)


_KEYED_MAX = 1000
_keyed: "OrderedDict[str, AsyncRateLimiter]" = OrderedDict()


def limiter_for(key_id: str) -> AsyncRateLimiter:
    """One bucket per API-key fingerprint (sha256(key)[:16])."""
    lim = _keyed.get(key_id)
    if lim is None:
        lim = _keyed[key_id] = AsyncRateLimiter(
            rpm=settings.gemini_rpm_limit, concurrency=settings.gemini_concurrency
        )
        while len(_keyed) > _KEYED_MAX:
            _keyed.popitem(last=False)
    else:
        _keyed.move_to_end(key_id)
    return lim
