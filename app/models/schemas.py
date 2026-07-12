"""
ArenaIQ — Pydantic schema models for HTTP request/response payloads.

Provides strict validation and serialization for all data crossing the
network boundary, with the following design decisions:

``extra='forbid'`` security design
    :class:`UserContext` is configured with ``ConfigDict(extra="forbid")``
    so that unrecognised fields in the request body raise an HTTP 422 error
    immediately, preventing parameter-pollution attacks.

Validation chain
    Pydantic field validators run in declaration order:
    1. ``_sanitize_question`` — strips control characters from free text.
    2. ``_normalize_needs`` — deduplicates and normalises the needs list.
    3. ``_validate_zone`` — verifies the zone exists in the loaded stadium.

Zone validator coupling
    ``_validate_zone`` calls :func:`~app.services.stadium_data.get_stadium`
    at validation time to check the supplied ``current_location`` against the
    live stadium fixture. This tight coupling is intentional: it ensures that
    invalid zone IDs are rejected with Pydantic's standard 422 response
    rather than propagating deeper into the routing engine.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from app.services.security import sanitize_text
from app.services.stadium_data import get_stadium
from app.utils.constants import MAX_QUESTION_LENGTH


class Language(StrEnum):
    """Supported UI and voice-output languages.

    Attributes:
        en: English.
        es: Spanish.
        fr: French.
    """
    en = "en"
    es = "es"
    fr = "fr"


class DestinationIntent(StrEnum):
    """The fan's desired destination category.

    Attributes:
        restroom: Restrooms / toilets.
        gate: Entry/exit gates.
        seat: The fan's ticketed seat.
        exit: Any stadium exit.
        first_aid: Medical facilities.
        concession: Food and beverage.
        guest_services: Help desks.
        water: Water fountains.
        sensory_room: Quiet sensory rooms.
    """
    restroom = "restroom"
    gate = "gate"
    seat = "seat"
    exit = "exit"
    first_aid = "first_aid"
    concession = "concession"
    guest_services = "guest_services"
    water = "water"
    sensory_room = "sensory_room"


class AccessibilityNeed(StrEnum):
    """Declared accessibility requirements.

    Attributes:
        none: No specific needs.
        wheelchair: Requires step-free routing.
        visual: Requires screen-reader optimized landmarks.
        hearing: Requires captioned visual instructions.
    """
    none = "none"
    wheelchair = "wheelchair"
    visual = "visual"
    hearing = "hearing"


class CrowdLevel(StrEnum):
    """Simulated congestion states.

    Attributes:
        low: Free-flowing traffic.
        medium: Moderate congestion.
        high: Severe congestion, triggers rerouting.
    """
    low = "low"
    medium = "medium"
    high = "high"


class AccessibilityMode(StrEnum):
    """Response rendering mode.

    Attributes:
        standard: Default visual UI.
        screen_reader: Optimised for screen readers with landmarks.
        captioned: Visual heavy for hearing impaired.
    """
    standard = "standard"
    screen_reader = "screen_reader"
    captioned = "captioned"


class UserContext(BaseModel):
    """The incoming request payload from the fan UI.

    Attributes:
        language: Requested output language.
        current_location: The zone ID the fan is currently in.
        destination_intent: The category of facility they want to reach.
        accessibility_needs: List of declared accessibility needs.
        minutes_to_kickoff: Integer minutes until match starts.
        ticket_section: Optional ticket section string (e.g. '112').
        question: Optional free-text question.
    """
    model_config = ConfigDict(extra="forbid")
    language: Language
    current_location: str
    destination_intent: DestinationIntent
    accessibility_needs: list[AccessibilityNeed] = Field(default_factory=lambda: [AccessibilityNeed.none])
    minutes_to_kickoff: int = Field(ge=-120, le=1440)
    ticket_section: str | None = Field(default=None, max_length=10)
    question: str | None = Field(default=None, max_length=MAX_QUESTION_LENGTH)

    @field_validator("question")
    @classmethod
    def _sanitize_question(cls, v: str | None, info: ValidationInfo) -> str | None:
        """Sanitize the free-text question field.

        Args:
            v: Raw question string.
            info: Pydantic validation info.

        Returns:
            Sanitized string or None.

        Raises:
            ValueError: If sanitization fails.

        Example:
            >>> UserContext._sanitize_question("hello \\x00", info)
            'hello'
        """
        if v is None:
            return None
        _ = info
        return sanitize_text(v)

    @field_validator("accessibility_needs")
    @classmethod
    def _normalize_needs(
        cls, v: list[AccessibilityNeed], info: ValidationInfo
    ) -> list[AccessibilityNeed]:
        """Deduplicate and normalize the accessibility needs list.

        Args:
            v: Raw list of needs.
            info: Pydantic validation info.

        Returns:
            Normalized list of needs.

        Raises:
            ValueError: If parsing fails.

        Example:
            >>> UserContext._normalize_needs([AccessibilityNeed.wheelchair], info)
        """
        _ = info
        if not v:
            return [AccessibilityNeed.none]
        needs: set[AccessibilityNeed] = set(v)
        if AccessibilityNeed.none in needs and len(needs) > 1:
            needs.remove(AccessibilityNeed.none)
        return list(needs)

    @field_validator("current_location")
    @classmethod
    def _validate_zone(cls, v: str) -> str:
        """Validate that the supplied zone ID exists in the loaded stadium fixture.

        Calls :func:`~app.services.stadium_data.get_stadium` to access the
        in-memory stadium and checks whether ``v`` is a key in
        :attr:`~app.services.stadium_data.Stadium.zones`.

        Args:
            v: The raw ``current_location`` string from the request body.

        Returns:
            The validated zone ID string, unchanged.

        Raises:
            ValueError: If ``v`` is not a recognised zone ID in the stadium
                fixture, causing Pydantic to return an HTTP 422 response.

        Example:
            >>> UserContext._validate_zone("gate_a")
            'gate_a'
        """
        # Check against cached stadium if loaded.
        stadium = get_stadium()
        if v not in stadium.zones:
            raise ValueError("unknown zone")
        return v


class RouteStep(BaseModel):
    """A single step in the navigation route.

    Attributes:
        order: Step sequence number (1-indexed).
        from_zone: Origin zone ID for this step.
        to_zone: Destination zone ID for this step.
        means: Method of transit (walk, ramp, elevator, stairs).
        step_free: True if this edge is accessible.
        distance: Walking distance in metres.
        landmark: Optional localized landmark.
        instruction: Full localized natural-language instruction sentence.
    """
    order: int
    from_zone: str
    to_zone: str
    means: str
    step_free: bool
    distance: int
    landmark: str | None
    instruction: str


class FacilityInfo(BaseModel):
    """Public metadata for a stadium facility.

    Attributes:
        id: Unique facility identifier.
        name: Localized display name.
        type: Category type (e.g. restroom).
        zone: Zone ID where it is located.
        accessible: True if ADA compliant.
        landmark: Optional localized landmark description.
    """
    id: str
    name: str
    type: str
    zone: str
    accessible: bool
    landmark: str | None


class DecisionResult(BaseModel):
    """Internal facts container returned by the rules engine.

    Attributes:
        facility: Selected target facility info.
        route_steps: Ordered list of route steps.
        crowd_level: Resolved crowd index.
        language: Language for strings.
        accessibility_mode: Decided UI presentation mode.
        landmark_based: True if route uses landmarks heavily.
        hurry: True if kickoff is imminent.
        alternatives_note: Optional notice if crowd-swapped.
        urgency: Optional urgency warning string.
    """
    facility: FacilityInfo
    route_steps: list[RouteStep]
    crowd_level: CrowdLevel
    language: Language
    accessibility_mode: AccessibilityMode
    landmark_based: bool
    hurry: bool
    alternatives_note: str | None
    urgency: str | None


class AssistResponse(BaseModel):
    """The outgoing HTTP response payload to the UI.

    Attributes:
        answer: The final natural language response (templated or LLM).
        route_steps: List of turn-by-turn steps.
        facility: Target facility metadata.
        crowd_level: Computed crowd status at destination.
        language: Selected language.
        accessibility_mode: Selected display mode.
        alternatives_note: Notice if rerouted for crowds.
        urgency: Notice if time-sensitive.
        used_llm: True if Gemini generated the answer string.
    """
    answer: str
    route_steps: list[RouteStep]
    facility: FacilityInfo
    crowd_level: CrowdLevel
    language: Language
    accessibility_mode: AccessibilityMode
    alternatives_note: str | None
    urgency: str | None
    used_llm: bool


class HealthResponse(BaseModel):
    """Response payload for the liveness probe.

    Attributes:
        status: Literal string 'ok'.
    """
    status: str
