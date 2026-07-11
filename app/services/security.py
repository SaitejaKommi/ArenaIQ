"""Security utilities: input sanitization and a per-IP token-bucket rate limiter.

These are deliberately dependency-free and in-memory so the app stays lean and
the behaviour is fully testable offline.
"""

from __future__ import annotations

import re
import threading
import time

_MAX_QUESTION_LEN = 280
_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_text(text: str) -> str:
    """Neutralise free-text user input before it is stored or shown to the LLM.

    Strips control characters (a common prompt-injection / log-forging vector),
    collapses runs of whitespace, trims, and hard-caps the length. The result is
    still treated strictly as *data* (never instructions) by the LLM layer.
    """
    # Drop control chars: anything below space (0x20) or DEL (0x7f), keeping none
    # of them — newlines/tabs are converted to spaces by the whitespace collapse.
    cleaned = "".join(ch for ch in text if ord(ch) >= 32 and ord(ch) != 127)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned[:_MAX_QUESTION_LEN]


class RateLimiter:
    """Thread-safe in-memory token-bucket rate limiter, keyed per client.

    Each key starts with ``capacity`` tokens and refills at
    ``refill_per_sec`` tokens/second. Each allowed request consumes one token.
    """

    def __init__(self, capacity: int, refill_per_sec: float, max_entries: int = 10_000) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._capacity = float(capacity)
        self._refill = float(refill_per_sec)
        self._max_entries = max_entries
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def _evict_idle(self) -> None:
        """Bound memory: drop the least-recently-seen IPs above ``max_entries``.

        Called under the lock. Evicting an idle bucket is safe — a fresh bucket
        starts full, which is the most lenient state, so we never wrongly block.
        """
        overflow = len(self._buckets) - self._max_entries
        if overflow <= 0:
            return
        # Sort by last-seen timestamp ascending (oldest first) and drop the overflow.
        for key in sorted(self._buckets, key=lambda k: self._buckets[k][1])[:overflow]:
            del self._buckets[key]

    def check(self, key: str) -> tuple[bool, float]:
        """Attempt to consume a token for ``key``.

        Returns ``(allowed, retry_after_seconds)``. ``retry_after_seconds`` is 0
        when allowed, otherwise the estimated wait until one token is available.
        """
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (self._capacity, now))
            # Refill based on elapsed time, capped at capacity.
            tokens = min(self._capacity, tokens + (now - last) * self._refill)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                allowed, retry_after = True, 0.0
            else:
                self._buckets[key] = (tokens, now)
                retry_after = (1.0 - tokens) / self._refill if self._refill > 0 else 60.0
                allowed = False
            self._evict_idle()
            return allowed, retry_after

    def reset(self) -> None:
        """Clear all buckets (used by tests)."""
        with self._lock:
            self._buckets.clear()
