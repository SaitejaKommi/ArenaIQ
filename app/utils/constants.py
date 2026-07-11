"""
ArenaIQ — Application-wide constants.

Centralises every magic number, threshold, and configuration literal used
across the ArenaIQ service layer to provide a single source of truth and
eliminate inline magic values throughout the codebase.

All values are declared as ``typing.Final`` so static analysis tools
(mypy, pyright) can verify they are never reassigned.

Typical usage::

    from app.utils.constants import (
        MAX_QUESTION_LENGTH,
        KICKOFF_IMMINENT_MINUTES,
        GEMINI_TEMPERATURE,
    )
"""

from __future__ import annotations

from typing import Final

# ============================================================
# INPUT SANITIZATION
# ============================================================

# ASCII printable range lower bound (inclusive) — characters below this are
# control characters (e.g. NUL, BEL, ESC) used in log-forging / injection.
ASCII_PRINTABLE_MIN: Final[int] = 32

# ASCII DEL character (127) — also a control character; excluded from input.
ASCII_DEL: Final[int] = 127

# Maximum number of characters accepted in the free-text question field.
# Must match the Pydantic field max_length in UserContext.question.
MAX_QUESTION_LENGTH: Final[int] = 280

# Maximum number of IP buckets kept in memory by the rate limiter.
# Entries beyond this cap are evicted oldest-first to bound RAM usage.
RATE_LIMITER_MAX_ENTRIES: Final[int] = 10_000

# ============================================================
# CROWD SIMULATION
# ============================================================

# Minutes before kickoff at which the crowd surge is considered *imminent*:
# gates and concourses jump +2 crowd levels in this window (0..10 min).
# Based on historical crowd-flow observations at large NFL/Soccer venues.
KICKOFF_IMMINENT_MINUTES: Final[int] = 10

# Minutes before kickoff that define the *pre-match* surge window (10..30 min).
# Crowd bumped by +1 level during this period, before the imminent window.
KICKOFF_PRE_MATCH_MINUTES: Final[int] = 30

# Crowd index increment applied during the imminent pre-kickoff window.
CROWD_BUMP_IMMINENT: Final[int] = 2

# Crowd index increment applied during the pre-match surge window.
CROWD_BUMP_PRE_MATCH: Final[int] = 1

# Crowd index reduction applied to gate zones once the match is underway
# (minutes_to_kickoff < 0) because fans have entered and gates clear out.
CROWD_RELIEF_IN_PLAY: Final[int] = 1

# Minutes-to-kickoff threshold for showing an urgency banner to fans heading
# to time-sensitive destinations (gate / seat).
KICKOFF_URGENCY_MINUTES: Final[int] = 15

# ============================================================
# LLM / GEMINI CONFIGURATION
# ============================================================

# Gemini generation temperature: 0.3 keeps answers factual and consistent.
# Lower values (→ 0) make outputs near-deterministic; 1.0 is fully creative.
GEMINI_TEMPERATURE: Final[float] = 0.3

# ============================================================
# ROUTING
# ============================================================

# Supported ISO 639-1 language codes for multilingual stadium assistance.
SUPPORTED_LANGUAGES: Final[list[str]] = ["en", "es", "fr"]

# Default language code used when a requested language is not supported.
DEFAULT_LANGUAGE: Final[str] = "en"
