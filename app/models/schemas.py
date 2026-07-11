"""
ArenaIQ — Pydantic v2 request/response schemas, enumerations, and validators.

All external input reaches the application exclusively through
:class:`UserContext`, which enforces strict field constraints via Pydantic v2
validators. Unknown fields are rejected (``extra="forbid"``), enum values are
enforced at the type level, and the free-text ``question`` is sanitized by
:func:`~app.services.security.sanitize_text` before it is stored or forwarded
to the LLM.

Security note:
    The sanitized ``question`` is injected into the LLM prompt inside an
    explicitly delimited ``<user_question>`` block. The system prompt instructs
    the model to treat it as *data only*, never as instructions — this is the
    second layer of prompt-injection defence on top of input sanitization.

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

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Language(StrEnum):
    """Supported response languages.

    The three FIFA World Cup 2026 host-nation languages: English (USA/Canada),
    Spanish (Mexico), and French (Canada). All API responses, route step
    instructions, and facility names are fully localized in each language.
    """

    en = "en"
    es = "es"
    fr = "fr"


class AccessibilityNeed(StrEnum):
    """Declared accessibility needs that influence routing and response mode.

    ``wheelchair`` and ``visual`` trigger step-free routing (ramps/elevators
    only) and accessible-only facility filtering. ``hearing`` activates the
    ``captioned`` response mode that emphasizes visual signage. ``none``
    signals no special requirements.
    """

    wheelchair = "wheelchair"
    visual = "visual"
    hearing = "hearing"
    none = "none"


class DestinationIntent(StrEnum):
    """Fan's intended destination category.

    Maps to one or more concrete facility types in the stadium graph.
    ``seat`` is resolved specially from the ticket section number rather
    than by proximity-based matching.
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


class CrowdLevel(StrEnum):
    """Simulated crowd congestion level at a stadium zone.

    Derived by the crowd simulation module from the zone's base level and
    the current ``minutes_to_kickoff``. Values map directly to CSS classes
    in the frontend for colour-coded crowd indicators.
    """

    low = "low"
    medium = "medium"
    high = "high"


class AccessibilityMode(StrEnum):
    """Server-side presentation mode that drives how the UI renders the answer.

    ``screen_reader`` is activated by ``visual`` need — uses landmark-based
    instructions optimized for assistive technologies.
    ``captioned`` is activated by ``hearing`` need — emphasizes visible
    signage references and highlights the Sensory Room option.
    ``standard`` is the default for fans with no declared accessibility need.

    Note:
        The client also offers a purely visual "high-visibility" CSS theme
        toggle, which maps the ``visual`` need to ``screen_reader`` mode
        server-side.
    """

    standard = "standard"
    screen_reader = "screen_reader"
    captioned = "captioned"


class UserContext(BaseModel):
    """Structured fan context — the sole body of ``POST /api/assist``.

    Every field is validated on construction. Unknown fields are rejected
    (``extra="forbid"``) as a defence-in-depth measure. The ``question``
    field is sanitized via :func:`~app.services.security.sanitize_text`
    before the model instance is returned.

    Attributes:
        language: ISO 639-1 code for the desired response language.
        current_location: A valid stadium zone ID (validated against the
            live zone registry).
        destination_intent: The fan's intended destination category.
        accessibility_needs: Zero or more declared accessibility needs.
            Normalized so that ``none`` is dropped when real needs exist.
        ticket_section: Optional ticket section identifier (e.g. ``"134"``).
            Used to resolve ``seat`` intent to upper/lower bowl.
        minutes_to_kickoff: Minutes until kickoff; negative values mean
            the match is already underway. Drives crowd simulation.
        question: Optional free-text question sanitized and forwarded to
            the LLM. Treated strictly as data, never as instructions.
    """

    model_config = ConfigDict(extra="forbid")

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
        """Reject zone IDs that do not exist in the stadium fixture.

        Imported lazily to avoid a circular import at module load time.

        Args:
            value: The raw ``current_location`` string from the request body.

        Returns:
            The validated zone ID string, unchanged.

        Raises:
            ValueError: If ``value`` is not a recognised stadium zone ID.
        """
        from app.services.stadium_data import get_stadium

        if value not in get_stadium().zone_ids():
            raise ValueError(f"unknown zone id: {value!r}")
        return value

    @field_validator("accessibility_needs")
    @classmethod
    def _normalize_needs(cls, needs: list[AccessibilityNeed]) -> list[AccessibilityNeed]:
        """Deduplicate needs and drop ``none`` when real needs are present.

        Ensures the downstream rules engine receives a clean, canonical set.
        If the list would be empty after normalization, ``[none]`` is restored
        so downstream code can always rely on a non-empty list.

        Args:
            needs: Raw list of :class:`AccessibilityNeed` values from input.

        Returns:
            A sorted, deduplicated list of :class:`AccessibilityNeed` values.
            ``none`` is removed when any real need (wheelchair/visual/hearing)
            is present. Returns ``[none]`` if all real needs are removed.
        """
        unique = set(needs)
        # ``none`` is meaningless alongside a real need; drop it.
        if AccessibilityNeed.none in unique and len(unique) > 1:
            unique.discard(AccessibilityNeed.none)
        if not unique:
            unique = {AccessibilityNeed.none}
        return sorted(unique, key=lambda n: n.value)

    @field_validator("question")
    @classmethod
    def _sanitize_question(cls, value: str | None) -> str | None:
        """Strip control characters and collapse whitespace in the question.

        Delegates to :func:`~app.services.security.sanitize_text`. Returns
        ``None`` if the sanitized result is an empty string so that the
        LLM path is not triggered by an effectively empty question.

        Args:
            value: Raw question string from the request body, or ``None``.

        Returns:
            A sanitized string with control characters removed and whitespace
            collapsed, or ``None`` if the result would be empty.
        """
        if value is None:
            return None
        from app.services.security import sanitize_text

        cleaned = sanitize_text(value)
        return cleaned or None


class RouteStep(BaseModel):
    """One leg of a navigation route with an accessibility-aware instruction.

    Each step describes movement between two zones via a specific travel
    means (walk, ramp, elevator, or stairs). The ``instruction`` field
    contains a fully localized, human-readable direction string.

    Attributes:
        order: 1-based step index within the route.
        from_zone: Zone ID of the departure point.
        to_zone: Zone ID of the arrival point.
        means: Travel means string (``"walk"``, ``"ramp"``, ``"elevator"``,
            ``"stairs"``).
        step_free: ``True`` if this leg is navigable without steps.
        distance: Approximate walking distance for this leg in metres.
        landmark: Optional localized landmark description at the destination.
        instruction: Full localized direction instruction for this step.
    """

    order: int
    from_zone: str
    to_zone: str
    means: str
    step_free: bool
    distance: int
    landmark: str | None = None
    instruction: str


class FacilityInfo(BaseModel):
    """Public representation of a resolved stadium facility.

    Returned as part of :class:`AssistResponse` so the frontend can display
    facility metadata alongside the navigation instructions.

    Attributes:
        id: Unique facility identifier (e.g. ``"restroom_lower_se"``).
        name: Localized display name of the facility.
        type: Facility category string (e.g. ``"restroom"``, ``"gate"``).
        zone: Zone ID where the facility is located.
        accessible: ``True`` if the facility is wheelchair-accessible.
        landmark: Optional localized landmark description at the facility.
    """

    id: str
    name: str
    type: str
    zone: str
    accessible: bool
    landmark: str | None = None


class DecisionResult(BaseModel):
    """Internal, fully deterministic result of the rules engine (pre-phrasing).

    Produced by :func:`~app.services.context_engine.build_decision` before
    any LLM is involved. Contains all resolved facts: target facility, route,
    crowd level, accessibility mode, and any urgency or alternatives note.
    Never crosses the API boundary — used only internally.

    Attributes:
        facility: Resolved target facility with localized metadata.
        route_steps: Ordered list of navigation legs to the facility.
        crowd_level: Simulated crowd level at the target facility zone.
        language: Requested response language.
        accessibility_mode: Presentation mode driven by accessibility needs.
        landmark_based: ``True`` when the route uses landmark instructions
            (activated by the ``visual`` accessibility need).
        hurry: ``True`` when kickoff is imminent and the intent is time-sensitive.
        alternatives_note: Localized note explaining a crowd-avoidance swap,
            or ``None`` if the primary facility was selected.
        urgency: Localized urgency banner text, or ``None`` if not hurried.
    """

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
    """Response body of ``POST /api/assist``.

    Combines the phrased natural-language answer with all the structured
    route and facility data the frontend needs to render the full response
    panel, including crowd indicators and route step cards.

    Attributes:
        answer: Localized natural-language answer paragraph (from templates
            or the Gemini LLM when a question is provided).
        route_steps: Ordered list of navigation legs to the facility.
        facility: Resolved target facility with localized metadata.
        crowd_level: Simulated crowd level at the target facility zone.
        language: Language used for all localized text in this response.
        accessibility_mode: Presentation mode communicated to the frontend.
        alternatives_note: Localized crowd-avoidance note, or ``None``.
        urgency: Localized urgency banner text, or ``None``.
        used_llm: ``True`` if Gemini generated the ``answer``; ``False``
            when the templated short-circuit path was taken.
    """

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
    """Liveness probe response body for ``GET /health``.

    Attributes:
        status: Always ``"ok"`` when the application is running and healthy.
    """

    status: str = "ok"
