"""Token-bucket rate limiter for Gemini's 15 RPM free tier.

Single global instance per process. Async-safe.
"""
from __future__ import annotations

import asyncio
import time
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
