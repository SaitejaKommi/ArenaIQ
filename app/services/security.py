"""
ArenaIQ — Input sanitization and per-IP token-bucket rate limiter.

# ============================================================
# ARCHITECTURAL DECISION: IN-MEMORY DEFENCES
# ============================================================
# Both utilities (sanitization and rate limiting) are deliberately
# dependency-free and in-memory. This keeps the application lean,
# guarantees zero network I/O overhead on the critical path, and
# makes the behaviour fully testable offline.
#
# Rate limiting uses a token bucket algorithm to gracefully handle
# traffic bursts. Oldest entries are evicted when capacity is reached,
# ensuring memory usage remains strictly bounded (O(N) space) even
# under adversarial traffic patterns.
# ============================================================
"""

from __future__ import annotations

import re
import threading
import time

from app.utils.constants import (
    ASCII_DEL,
    ASCII_PRINTABLE_MIN,
    MAX_QUESTION_LENGTH,
    RATE_LIMITER_MAX_ENTRIES,
)

_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_text(text: str) -> str:
    """Neutralize free-text user input before storage or LLM exposure.

    Strips ASCII control characters (common vectors for prompt-injection)
    and collapses whitespace. The length is strictly capped.

    Args:
        text: Raw free-text string from the user request body.

    Returns:
        A sanitized string with control characters removed, whitespace
        collapsed to single spaces, and length hard-capped.

    Raises:
        TypeError: If text is not a string.

    Example:
        >>> sanitize_text("Hello \\n\\n World! \\x00")
        'Hello World!'
    """
    cleaned: str = "".join(
        ch for ch in text if ord(ch) >= ASCII_PRINTABLE_MIN and ord(ch) != ASCII_DEL
    )
    return _WHITESPACE_RE.sub(" ", cleaned).strip()[:MAX_QUESTION_LENGTH]


class RateLimiter:
    """Thread-safe in-memory token-bucket rate limiter.

    Keys are typically client IPs. Each IP starts with `capacity` tokens.
    Memory is bounded by `max_entries`; oldest are evicted to prevent OOM.

    Attributes:
        capacity: Maximum tokens per bucket (float cast internally).
        refill: Token refill rate per second (float).
        max_entries: Max simultaneous tracking buckets.
    """

    def __init__(
        self,
        capacity: int,
        refill_per_sec: float,
        max_entries: int = RATE_LIMITER_MAX_ENTRIES,
    ) -> None:
        """Initialize the token-bucket parameters and state.

        Args:
            capacity: Maximum number of tokens per bucket (>= 1).
            refill_per_sec: Rate at which tokens are added per second.
            max_entries: Maximum number of tracking buckets held in memory.

        Raises:
            ValueError: If capacity < 1 or max_entries < 1.

        Example:
            >>> limiter = RateLimiter(capacity=30, refill_per_sec=0.5)
            >>> allowed, wait = limiter.check("192.168.1.1")
        """
        if capacity < 1 or max_entries < 1:
            raise ValueError("capacity and max_entries must be >= 1")
        self.capacity: float = float(capacity)
        self.refill: float = float(refill_per_sec)
        self.max_entries: int = max_entries
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock: threading.Lock = threading.Lock()

    def _evict_idle(self) -> None:
        """Evict oldest-accessed IPs when the bucket map exceeds capacity.

        Called safely under lock. Evicted IPs simply start with full
        tokens on their next request.

        Args:
            None

        Returns:
            None

        Raises:
            None

        Example:
            >>> limiter._evict_idle()  # called internally under lock
        """
        overflow: int = len(self._buckets) - self.max_entries
        if overflow > 0:
            for key in sorted(self._buckets, key=lambda k: self._buckets[k][1])[:overflow]:
                del self._buckets[key]

    def _compute_refill(self, key: str, now: float) -> float:
        """Calculate the available tokens for a bucket at current time.

        Args:
            key: IP identifier string.
            now: Monotonic timestamp in seconds.

        Returns:
            The newly calculated token balance, capped at max capacity.

        Raises:
            None

        Example:
            >>> tokens = limiter._compute_refill("10.0.0.1", time.monotonic())
            >>> tokens <= limiter.capacity
            True
        """
        tokens, last = self._buckets.get(key, (self.capacity, now))
        return min(self.capacity, tokens + (now - last) * self.refill)

    def check(self, key: str) -> tuple[bool, float]:
        """Attempt to consume one token from the bucket for key.

        Args:
            key: Client identifier string, typically the remote IP.

        Returns:
            A tuple of (allowed_bool, retry_after_seconds). If allowed,
            retry_after is 0.0.

        Raises:
            None

        Example:
            >>> allowed, wait = limiter.check("10.0.0.1")
            >>> if not allowed: print(f"Wait {wait}s")
        """
        now: float = time.monotonic()
        with self._lock:
            tokens = self._compute_refill(key, now)
            allowed = tokens >= 1.0
            self._buckets[key] = (tokens - 1.0 if allowed else tokens, now)
            retry = 0.0 if allowed else ((1.0 - tokens) / self.refill if self.refill > 0 else 60.0)
            self._evict_idle()
            return allowed, retry

    def reset(self) -> None:
        """Clear all tracked IP buckets.

        Restores a fully fresh state. Intended exclusively for tests.

        Args:
            None

        Returns:
            None

        Raises:
            None

        Example:
            >>> limiter.reset()
        """
        with self._lock:
            self._buckets.clear()
