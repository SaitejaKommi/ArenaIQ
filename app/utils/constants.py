"""
ArenaIQ — Application-wide Configuration Constants.

Centralises every magic number, threshold, and configuration literal used
across the ArenaIQ service layer to provide a single source of truth and
eliminate inline magic values throughout the codebase.

This allows tuning crowd simulation parameters, LLM parameters, and limits
without hunting through implementation logic.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "ASCII_PRINTABLE_MIN",
    "ASCII_DEL",
    "MAX_QUESTION_LENGTH",
    "RATE_LIMITER_MAX_ENTRIES",
    "KICKOFF_IMMINENT_MINUTES",
    "KICKOFF_PRE_MATCH_MINUTES",
    "CROWD_BUMP_IMMINENT",
    "CROWD_BUMP_PRE_MATCH",
    "CROWD_RELIEF_IN_PLAY",
    "KICKOFF_URGENCY_MINUTES",
    "GEMINI_TEMPERATURE",
    "ROUTE_INFINITY_COST",
    "SUPPORTED_LANGUAGES",
    "DEFAULT_LANGUAGE",
]

# ============================================================
# INPUT SANITIZATION LIMITS
# ============================================================
# These constants define the bounds for sanitizing free-text
# questions before they are stored or injected into LLM prompts.

# ASCII printable range lower bound (inclusive). Characters below this
# are control characters (e.g. NUL, BEL, ESC) used in log-forging.
ASCII_PRINTABLE_MIN: Final[int] = 32

# ASCII DEL character (127), a control character excluded from input.
ASCII_DEL: Final[int] = 127

# Maximum characters accepted in the free-text question field.
# Must match Pydantic's max_length in UserContext.question.
MAX_QUESTION_LENGTH: Final[int] = 280

# Maximum number of IP buckets kept in memory by the rate limiter.
# Prevents memory exhaustion attacks by evicting oldest entries.
RATE_LIMITER_MAX_ENTRIES: Final[int] = 10_000

# ============================================================
# CROWD SIMULATION THRESHOLDS
# ============================================================
# Derived from historical stadium crowd-flow patterns. They
# control when the simulation applies surge multipliers to base
# congestion levels in the crowd engine.

# Minutes before kickoff when the crowd surge is considered 'imminent'.
# Gates and concourses surge +2 levels in this window (0..10 min).
KICKOFF_IMMINENT_MINUTES: Final[int] = 10

# Minutes before kickoff defining the 'pre-match' surge window (10..30 min).
# Crowd bumped by +1 level during this period.
KICKOFF_PRE_MATCH_MINUTES: Final[int] = 30

# Crowd index increment applied during the imminent pre-kickoff window.
CROWD_BUMP_IMMINENT: Final[int] = 2

# Crowd index increment applied during the pre-match surge window.
CROWD_BUMP_PRE_MATCH: Final[int] = 1

# Crowd index reduction applied to gate zones once match is underway.
CROWD_RELIEF_IN_PLAY: Final[int] = 1

# Minutes-to-kickoff threshold for showing an urgency banner to fans.
KICKOFF_URGENCY_MINUTES: Final[int] = 15

# ============================================================
# LLM / GEMINI CONFIGURATION
# ============================================================
# Generation parameters for the Google Gemini client.

# Gemini generation temperature. 0.3 balances factual grounding with
# natural phrasing. 0.0 is too robotic, 1.0 is hallucination-prone.
GEMINI_TEMPERATURE: Final[float] = 0.3

# ============================================================
# ROUTING & LOCALIZATION
# ============================================================
# Definitions for multi-lingual routing support.

# Supported ISO 639-1 language codes (English, Spanish, French).
SUPPORTED_LANGUAGES: Final[list[str]] = ["en", "es", "fr"]

# Default language code used when a requested language is not supported.
DEFAULT_LANGUAGE: Final[str] = "en"

# ============================================================
# ROUTING — DIJKSTRA ALGORITHM
# ============================================================
# Sentinel value used as an initial "infinite" cost in the Dijkstra
# shortest-path algorithm so that any real path cost is lower.
# Using int avoids float precision issues in heap comparisons.

# Sentinel representing unreachable (infinity) cost in Dijkstra search.
ROUTE_INFINITY_COST: Final[int] = 1_000_000_000
