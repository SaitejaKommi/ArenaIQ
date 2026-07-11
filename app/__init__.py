"""
ArenaIQ — Multilingual, Accessible Stadium Assistant for FIFA World Cup 2026.

This package implements the full ArenaIQ backend: a FastAPI application that
provides AI-powered stadium navigation, real-time crowd simulation, and
accessibility-aware routing for fans attending matches at MetLife Stadium
(New York/New Jersey), the primary venue for the 2026 FIFA World Cup Final.

Architecture overview:
    * ``app.main``              — FastAPI application factory and HTTP endpoints.
    * ``app.config``            — Pydantic-settings configuration (env-driven).
    * ``app.logging_conf``      — Privacy-preserving structured logging setup.
    * ``app.models.schemas``    — Pydantic v2 request/response models and enums.
    * ``app.services``          — All business-logic services (see sub-package).
    * ``app.utils.constants``   — Centralised ``Final`` constants.

Security model:
    All user-supplied free text is sanitized before storage or LLM exposure.
    The decision engine resolves every routing fact deterministically from
    structured data *before* any LLM involvement, making prompt injection
    unable to alter routes, crowd data, or facility information.

Typical usage::

    # Start the server with uvicorn:
    # uvicorn app.main:app --host 0.0.0.0 --port 8000

    # Or import the factory directly in tests:
    from app.main import create_app
    app = create_app(settings=my_test_settings)
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = [
    "config",
    "logging_conf",
    "main",
    "models",
    "services",
    "utils",
]
