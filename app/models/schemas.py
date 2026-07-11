"""Pydantic v2 request/response models and enums.

All external input flows through :class:`UserContext`, which constrains every
field with enums, bounds and validators. Unknown zone ids and unknown fields are
rejected, and the free-text ``question`` is sanitized on the way in.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Language(StrEnum):
    """Supported response languages — the three FIFA WC 2026 host-nation languages
    (USA/Canada → English/French, Mexico → Spanish)."""

    en = "en"
    es = "es"
    fr = "fr"


class AccessibilityNeed(StrEnum):
    wheelchair = "wheelchair"
    visual = "visual"
    hearing = "hearing"
    none = "none"


class DestinationIntent(StrEnum):
    restroom = "restroom"
    gate = "gate"
    seat = "seat"
    exit = "exit"
    first_aid = "first_aid"
    concession = "concession"
    guest_services = "guest_services"
    water = "water"
    sensory_room = "sensory_room"


class CrowdLevel(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class AccessibilityMode(StrEnum):
    """Server-side response mode driving how the UI presents the answer.

    (The client also offers a purely visual "high-visibility" CSS theme toggle,
    which maps to the ``visual`` need → ``screen_reader`` mode server-side.)
    """

    standard = "standard"
    screen_reader = "screen_reader"  # visual need: landmark-based, SR-optimized
    captioned = "captioned"  # hearing need: emphasize visual signage / sensory room


class UserContext(BaseModel):
    """Structured fan context — the sole body of ``POST /api/assist``."""

    model_config = ConfigDict(extra="forbid")  # reject unknown fields (defense in depth)

    language: Language = Language.en
    current_location: str = Field(..., min_length=1, max_length=40)
    destination_intent: DestinationIntent
    accessibility_needs: list[AccessibilityNeed] = Field(
        default_factory=lambda: [AccessibilityNeed.none]
    )
    ticket_section: str | None = Field(
        default=None, max_length=8, pattern=r"^[A-Za-z0-9\- ]{1,8}$"
    )
    minutes_to_kickoff: int = Field(..., ge=-120, le=1440)
    question: str | None = Field(default=None, max_length=280)

    @field_validator("current_location")
    @classmethod
    def _zone_must_exist(cls, value: str) -> str:
        # Imported lazily to avoid a circular import at module load time.
        from app.services.stadium_data import get_stadium

        if value not in get_stadium().zone_ids():
            raise ValueError(f"unknown zone id: {value!r}")
        return value

    @field_validator("accessibility_needs")
    @classmethod
    def _normalize_needs(cls, needs: list[AccessibilityNeed]) -> list[AccessibilityNeed]:
        unique = set(needs)
        # "none" is meaningless alongside a real need; drop it.
        if AccessibilityNeed.none in unique and len(unique) > 1:
            unique.discard(AccessibilityNeed.none)
        if not unique:
            unique = {AccessibilityNeed.none}
        return sorted(unique, key=lambda n: n.value)

    @field_validator("question")
    @classmethod
    def _sanitize_question(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from app.services.security import sanitize_text

        cleaned = sanitize_text(value)
        return cleaned or None


class RouteStep(BaseModel):
    """One leg of a route, with an accessibility-aware, localized instruction."""

    order: int
    from_zone: str
    to_zone: str
    means: str
    step_free: bool
    distance: int
    landmark: str | None = None
    instruction: str


class FacilityInfo(BaseModel):
    """Public representation of a resolved facility."""

    id: str
    name: str
    type: str
    zone: str
    accessible: bool
    landmark: str | None = None


class DecisionResult(BaseModel):
    """Internal, deterministic result of the rules engine (pre-phrasing)."""

    facility: FacilityInfo
    route_steps: list[RouteStep]
    crowd_level: CrowdLevel
    language: Language
    accessibility_mode: AccessibilityMode
    landmark_based: bool = False
    hurry: bool = False
    alternatives_note: str | None = None
    urgency: str | None = None


class AssistResponse(BaseModel):
    """Response body of ``POST /api/assist``."""

    answer: str
    route_steps: list[RouteStep]
    facility: FacilityInfo
    crowd_level: CrowdLevel
    language: Language
    accessibility_mode: AccessibilityMode
    alternatives_note: str | None = None
    urgency: str | None = None
    used_llm: bool


class HealthResponse(BaseModel):
    status: str = "ok"
