"""In-memory sliding-window attempt limiter for the login/signup routes.

Per process: with several workers each keeps its own window, which is fine for
slowing down password guessing on a single small instance. The key map is
bounded so a flood of distinct keys (spoofed emails, many IPs) cannot grow
memory without limit.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable


class SlidingWindow:
    def __init__(
        self,
        *,
        limit: int,
        window_s: float,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_s = window_s
        self.max_keys = max_keys
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def __len__(self) -> int:
        return len(self._hits)

    def hit(self, key: str) -> bool:
        """Record an attempt for ``key``; False (and not recorded) if over limit."""
        now = self._clock()
        q = self._hits.get(key)
        if q is not None:
            while q and q[0] <= now - self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return False
        else:
            self._make_room(now)
            q = self._hits[key] = deque()
        q.append(now)
        return True

    def _make_room(self, now: float) -> None:
        if len(self._hits) < self.max_keys:
            return
        cutoff = now - self.window_s
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= cutoff]:
            del self._hits[k]
        # Still full: drop the keys whose latest attempt is oldest.
        while len(self._hits) >= self.max_keys:
            oldest = min(self._hits, key=lambda k: self._hits[k][-1])
            del self._hits[oldest]

    def clear(self) -> None:
        self._hits.clear()
