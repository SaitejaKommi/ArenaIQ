"""
ArenaIQ — Pydantic Models Package.

Contains all Pydantic v2 request/response schemas, enumerations, and
validators that define the public API contract for ArenaIQ.

Modules:
    schemas: Request body (``UserContext``), response body (``AssistResponse``),
        intermediate results (``DecisionResult``), route steps (``RouteStep``),
        facility info (``FacilityInfo``), and enum types (``Language``,
        ``AccessibilityNeed``, ``DestinationIntent``, ``CrowdLevel``,
        ``AccessibilityMode``).

All external input is validated and sanitized at the schema boundary before
any business logic executes, enforcing ArenaIQ's defence-in-depth strategy.

Typical usage::

    from app.models.schemas import UserContext, AssistResponse
    ctx = UserContext(
        language="en",
        current_location="gate_a",
        destination_intent="restroom",
        minutes_to_kickoff=20,
    )
"""

from __future__ import annotations

__all__ = ["schemas"]
