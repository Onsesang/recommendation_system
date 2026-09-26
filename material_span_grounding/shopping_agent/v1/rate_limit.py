"""In-memory sliding-window rate limits for the public API.

Registration and login are limited per client IP, agent messages per user (each
message costs OpenAI calls). Limits live in `configs/v1.json` under `rate_limits`.
The counters are per process and reset on restart, which is enough for a single
demo server; a multi-process deployment would move them to a shared store.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Any, Callable


class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"요청이 너무 많습니다. {retry_after}초 후 다시 시도해주세요.")
        self.retry_after = retry_after


class RateLimiter:
    def __init__(self, rules: dict[str, dict[str, Any]], clock: Callable[[], float] = time.monotonic) -> None:
        self.rules = {
            name: (int(rule["limit"]), float(rule["window_seconds"]))
            for name, rule in rules.items()
            if isinstance(rule, dict) and "limit" in rule
        }
        self.clock = clock
        self.lock = threading.Lock()
        self.hits: dict[tuple[str, str], deque[float]] = {}
        self._checks = 0

    def check(self, rule: str, key: str) -> None:
        """Record one hit for `key` under `rule`, or raise RateLimited without recording it."""
        if rule not in self.rules:
            return
        limit, window = self.rules[rule]
        now = self.clock()
        with self.lock:
            bucket = self.hits.setdefault((rule, key), deque())
            while bucket and bucket[0] <= now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                raise RateLimited(max(1, math.ceil(bucket[0] + window - now)))
            bucket.append(now)
            self._checks += 1
            if self._checks % 1000 == 0:
                self._prune(now)

    def _prune(self, now: float) -> None:
        longest = max((window for _, window in self.rules.values()), default=0.0)
        for key in [key for key, bucket in self.hits.items() if not bucket or bucket[-1] <= now - longest]:
            del self.hits[key]


def client_ip(peer: str, headers: Any, trusted_proxies: set[str]) -> str:
    """The caller's IP; behind a local tunnel every peer is 127.0.0.1, so trust its forwarded header."""
    if peer in trusted_proxies:
        forwarded = headers.get("CF-Connecting-IP") or (headers.get("X-Forwarded-For") or "").split(",")[0]
        if forwarded and forwarded.strip():
            return forwarded.strip()
    return peer
