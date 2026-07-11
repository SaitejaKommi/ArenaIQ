"""
ArenaIQ — Input sanitization and per-IP token-bucket rate limiter.

Both utilities are deliberately dependency-free and in-memory, keeping the
application lean and the behaviour fully testable offline without any
network, database, or cache dependencies.

Sanitization:
    :func:`sanitize_text` removes ASCII control characters (a common vector
    for prompt-injection and log-forging attacks), collapses whitespace, and
    hard-caps the string length at :data:`~app.utils.constants.MAX_QUESTION_LENGTH`.

Rate limiting:
    :class:`RateLimiter` implements a token-bucket algorithm keyed by client
    IP address. Each IP starts with a full bucket of ``capacity`` tokens and
    earns ``refill_per_sec`` tokens per second. Every allowed request consumes
    exactly one token; requests arriving to an empty bucket receive HTTP 429.

    The bucket map is bounded by ``max_entries`` using an oldest-first eviction
    strategy so the limiter's RAM footprint stays constant under adversarial
    traffic patterns.

Typical usage::

    from app.services.security import sanitize_text, RateLimiter

    clean = sanitize_text(raw_question)
    limiter = RateLimiter(capacity=30, refill_per_sec=0.5)
    allowed, retry_after = limiter.check(client_ip)
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

    Strips ASCII control characters — anything below space (0x20) or the
    DEL character (0x7F) — which are common prompt-injection and
    log-forging vectors. Newlines and tabs are implicitly converted to
    spaces by the subsequent whitespace-collapse step.

    The result is still treated strictly as *data* (never as instructions)
    by the LLM layer, providing a second layer of injection defence on top
    of the prompt structure.

    Args:
        text: Raw free-text string from the user request body. May contain
            arbitrary Unicode characters including control characters.

    Returns:
        A sanitized string with control characters removed, runs of
        whitespace collapsed to a single space, leading/trailing whitespace
        stripped, and length hard-capped at
        :data:`~app.utils.constants.MAX_QUESTION_LENGTH` characters.

    Raises:
        TypeError: If ``text`` is not a string.
    """
    # Drop control chars: anything below space (ASCII_PRINTABLE_MIN=32) or
    # DEL (ASCII_DEL=127), keeping none of them — newlines/tabs become
    # spaces via the whitespace collapse below.
    cleaned = "".join(
        ch for ch in text if ord(ch) >= ASCII_PRINTABLE_MIN and ord(ch) != ASCII_DEL
    )
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned[:MAX_QUESTION_LENGTH]


class RateLimiter:
    """Thread-safe in-memory token-bucket rate limiter, keyed per client IP.

    Each IP key starts with ``capacity`` tokens and refills continuously at
    ``refill_per_sec`` tokens per second up to the capacity ceiling. Each
    allowed request consumes exactly one token. When a key's bucket is
    empty the request is rejected and the caller is told how long to wait.

    Memory is bounded: when the number of tracked IPs exceeds ``max_entries``,
    the oldest-accessed entries are evicted. Evicted entries are treated as
    fresh (full bucket) on their next request — this is the most lenient
    possible state, so eviction never causes incorrect blocking.

    Thread safety:
        All bucket mutations are performed inside a ``threading.Lock`` so
        the limiter is safe to share across concurrent ASGI worker tasks.
    """

    def __init__(
        self,
        capacity: int,
        refill_per_sec: float,
        max_entries: int = RATE_LIMITER_MAX_ENTRIES,
    ) -> None:
        """Initialise the rate limiter with the given token-bucket parameters.

        Args:
            capacity: Maximum number of tokens per bucket, and the starting
                token count for every new IP. Must be >= 1.
            refill_per_sec: Rate at which tokens are added to each bucket
                per second. Zero disables refilling (one-shot buckets).
            max_entries: Upper bound on the number of IP buckets held in
                memory simultaneously. Defaults to
                :data:`~app.utils.constants.RATE_LIMITER_MAX_ENTRIES`.

        Raises:
            ValueError: If ``capacity`` < 1 or ``max_entries`` < 1.
        """
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._capacity = float(capacity)
        self._refill = float(refill_per_sec)
        self._max_entries = max_entries
        # Each value is (current_tokens: float, last_seen_monotonic: float).
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def _evict_idle(self) -> None:
        """Evict oldest-accessed IPs when the bucket map exceeds its capacity.

        Called under the lock. Oldest entries are those with the earliest
        ``last_seen`` timestamp. Evicting a bucket is safe: the evicted IP
        will start fresh (full tokens) on its next request, which is the
        most lenient possible state and never causes a wrongful block.

        Returns:
            None
        """
        overflow = len(self._buckets) - self._max_entries
        if overflow <= 0:
            return
        # Sort ascending by last-seen timestamp; drop the ``overflow`` oldest.
        for key in sorted(self._buckets, key=lambda k: self._buckets[k][1])[:overflow]:
            del self._buckets[key]

    def check(self, key: str) -> tuple[bool, float]:
        """Attempt to consume one token from the bucket for ``key``.

        Refills the bucket based on elapsed wall-clock time since the last
        access, caps at ``capacity``, then either consumes a token (allowed)
        or returns the estimated wait time in seconds (rejected).

        Args:
            key: Client identifier string, typically the remote IP address.
                A new, full bucket is created automatically for unknown keys.

        Returns:
            A two-tuple ``(allowed, retry_after_seconds)`` where:
            - ``allowed`` is ``True`` if the request may proceed.
            - ``retry_after_seconds`` is ``0.0`` when allowed, otherwise
              the estimated seconds until one token becomes available.

        Raises:
            ZeroDivisionError: Cannot occur — zero refill rate is handled
                by falling back to ``retry_after = 60.0`` seconds.
        """
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (self._capacity, now))
            # Refill based on elapsed time since last access, capped at capacity.
            tokens = min(self._capacity, tokens + (now - last) * self._refill)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                allowed, retry_after = True, 0.0
            else:
                self._buckets[key] = (tokens, now)
                # Estimate wait: tokens needed = 1 - current_tokens; rate = refill.
                retry_after = (1.0 - tokens) / self._refill if self._refill > 0 else 60.0
                allowed = False
            self._evict_idle()
            return allowed, retry_after

    def reset(self) -> None:
        """Clear all tracked IP buckets, restoring a fully fresh state.

        Intended for use in tests to guarantee isolation between test cases
        that share a limiter instance.

        Returns:
            None
        """
        with self._lock:
            self._buckets.clear()
