"""Sliding-window rate limiter.

For each key (a reporter, an IP address) we keep a queue of the timestamps of its recent
requests. On every request:
  1. drop timestamps older than the window from the front of the queue,
  2. if the queue still holds `limit` timestamps, refuse,
  3. otherwise record this request at the back.

Why a sliding window: a fixed window ("10 per clock hour") lets someone send 10 at 10:59
and 10 more at 11:00, which is 20 in two minutes. A sliding window always looks at the
last `window` seconds, so that burst is impossible.

Why a deque: removing old timestamps from the front and adding new ones at the back are
both O(1). Each timestamp is added once and removed once, so a check is O(1) amortised.

Tradeoffs (said out loud in interviews):
  - State lives in this process's memory. It resets on restart and is NOT shared between
    several server instances. The production fix is Redis (a sorted set per key, or a
    counter with expiry), so every instance sees the same counts.
  - Memory is O(limit) per active key. Keys that go quiet are swept away periodically.
"""

import math
import threading
import time
from collections import deque
from typing import Callable


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock  # injectable so tests can control time instead of sleeping
        self._hits: dict[str, deque[float]] = {}
        # FastAPI runs normal (def) endpoints on a thread pool, so two requests can touch the
        # same queue at once. The lock makes "check then record" one indivisible step.
        self._lock = threading.Lock()
        self._calls = 0

    def check(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds). Records the request only if allowed."""
        with self._lock:
            now = self._clock()
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()

            if len(hits) >= self.limit:
                # The oldest request leaves the window first; that's when a slot frees up.
                retry_after = math.ceil(hits[0] + self.window - now)
                return False, max(retry_after, 1)

            hits.append(now)
            self._calls += 1
            if self._calls % 1000 == 0:
                self._sweep(now)
            return True, 0

    def _sweep(self, now: float) -> None:
        """Forget keys with no requests inside the window, so memory doesn't grow forever."""
        stale = [k for k, q in self._hits.items() if not q or q[-1] <= now - self.window]
        for k in stale:
            del self._hits[k]

    def tracked_keys(self) -> int:
        return len(self._hits)
