"""Process-wide throttle and circuit breaker shared by every MT request.

* at most ``MT_RPS`` requests per second, across all jobs;
* a request that fails with 429/5xx is retried with exponential backoff
  (max ``MAX_TRIES`` attempts);
* a request that exhausts its retries counts as a "block". After
  ``BREAKER_THRESHOLD`` consecutive blocks all MT pauses for ``BREAKER_PAUSE_S``
  (15 minutes) and a loud error is logged. A success resets the count.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

import httpx

from ..common.config import settings
from ..common.logging import get_logger
from .provider import MTBlocked, MTError

log = get_logger(__name__)

MAX_TRIES = 5
BACKOFF_BASE_S = 2.0
BREAKER_THRESHOLD = 3
BREAKER_PAUSE_S = 15 * 60

# Tests replace these to run without real time passing.
_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
_now: Callable[[], float] = time.monotonic

_next_slot = 0.0
_blocks = 0
_paused_until = 0.0
_lock: asyncio.Lock | None = None
_lock_loop: asyncio.AbstractEventLoop | None = None


def reset() -> None:
    global _next_slot, _blocks, _paused_until, _lock, _lock_loop
    _next_slot = 0.0
    _blocks = 0
    _paused_until = 0.0
    _lock = None
    _lock_loop = None


def paused() -> bool:
    return _now() < _paused_until


def pause_remaining_s() -> float:
    return max(0.0, _paused_until - _now())


def _get_lock() -> asyncio.Lock:
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock, _lock_loop = asyncio.Lock(), loop
    return _lock


async def _wait_turn() -> None:
    global _next_slot
    interval = 1.0 / max(settings.mt_rps, 0.001)
    async with _get_lock():
        now = _now()
        wait = _next_slot - now
        _next_slot = max(now, _next_slot) + interval
    if wait > 0:
        await _sleep(wait)


def _retryable(e: Exception) -> bool:
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        return code == 429 or code >= 500
    return isinstance(e, httpx.TransportError)


async def call(fn: Callable[[], Awaitable[object]]):
    """Run one provider request under the throttle, retries, and breaker.

    ``fn`` performs the HTTP call and raises ``httpx`` errors via
    ``raise_for_status``. Non-retryable errors become ``MTError`` immediately.
    """
    global _blocks, _paused_until
    if paused():
        raise MTBlocked(f"machine translation paused for {int(pause_remaining_s())}s")
    last: Exception | None = None
    for attempt in range(MAX_TRIES):
        await _wait_turn()
        try:
            out = await fn()
            _blocks = 0
            return out
        except MTError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            if not _retryable(e):
                raise MTError(f"translation request failed: {e}") from e
            if attempt < MAX_TRIES - 1:
                await _sleep(BACKOFF_BASE_S * (2**attempt))
    _blocks += 1
    if _blocks >= BREAKER_THRESHOLD:
        _paused_until = _now() + BREAKER_PAUSE_S
        _blocks = 0
        log.error(
            "mt.circuit_open", pause_minutes=BREAKER_PAUSE_S // 60,
            msg="provider keeps refusing requests; machine translation paused",
        )
    raise MTBlocked(f"provider refused {MAX_TRIES} attempts: {last}")
