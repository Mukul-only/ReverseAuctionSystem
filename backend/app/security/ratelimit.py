"""In-memory sliding-window rate limiting.

Suitable for a single-process demo. A multi-instance deployment would back
this with Redis so limits are shared across workers.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int


class SlidingWindowLimiter:
    def __init__(self, *, limit: int, window_seconds: int) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("limit and window_seconds must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> RateLimitResult:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= self.limit:
                retry_after = max(1, math.ceil(bucket[0] + self.window_seconds - now))
                return RateLimitResult(
                    allowed=False, remaining=0, retry_after=retry_after
                )

            bucket.append(now)
            return RateLimitResult(
                allowed=True, remaining=self.limit - len(bucket), retry_after=0
            )

    def clear(self) -> None:
        """Drop all state. Used by tests."""
        with self._lock:
            self._hits.clear()