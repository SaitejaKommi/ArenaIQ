"""
ArenaIQ — Utilities Package.

Provides shared helper modules and application-wide constants used across
the ArenaIQ service layer.

Modules:
    constants: All ``typing.Final`` constants (magic numbers, thresholds,
        string literals) centralised for single-source-of-truth maintenance.

Typical usage::

    from app.utils.constants import MAX_QUESTION_LENGTH, GEMINI_TEMPERATURE
"""

from __future__ import annotations

__all__ = ["constants"]
