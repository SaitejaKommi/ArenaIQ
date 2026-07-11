"""
ArenaIQ — Services Package.

Contains all business-logic services that power the ArenaIQ stadium
intelligence platform. Services are deliberately dependency-free of each
other where possible, and every service is fully testable offline (no
network calls required).

Modules:
    context_engine: Core orchestrator that coordinates all services.
        Implements the rules-before-LLM architecture: all routing facts
        are resolved deterministically before the LLM is engaged.
    routing: Dijkstra shortest-path algorithm for stadium zone navigation.
        Supports both standard and step-free (wheelchair/visual) routing.
    crowd: Time-based crowd congestion simulation driven by minutes to
        kickoff. Deterministic and fully unit-testable.
    security: Input sanitization (ASCII control-char stripping) and a
        thread-safe per-IP token-bucket rate limiter.
    phrasing: Deterministic, offline natural-language response generation
        in English, Spanish, and French. Used as the MockLLM fallback.
    llm: Google Gemini client with graceful MockLLM fallback. The LLM
        only *phrases* pre-resolved facts — it cannot invent facilities.
    stadium_data: JSON fixture loading and in-memory stadium graph.
        All data is loaded once at startup and cached for the process
        lifetime.

Typical usage::

    from app.services.context_engine import run_assist
    from app.services.stadium_data import get_stadium
    from app.services.llm import MockLLM

    stadium = get_stadium()
    response = await run_assist(ctx, stadium, MockLLM())
"""

from __future__ import annotations

__all__ = [
    "context_engine",
    "crowd",
    "llm",
    "phrasing",
    "routing",
    "security",
    "stadium_data",
]
