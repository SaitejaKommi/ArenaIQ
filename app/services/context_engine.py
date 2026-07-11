"""
ArenaIQ — Context-driven decision engine: deterministic rules run before the LLM.

This module implements the core rules-before-LLM architecture that makes
ArenaIQ secure against prompt injection:

1. :func:`build_decision` resolves every routing fact deterministically from
   the structured :class:`~app.models.schemas.UserContext` — target facility,
   accessible route, crowd level, accessibility mode, urgency — with **zero**
   LLM involvement. Because the decision never depends on the free-text
   ``question``, no injected instruction in that field can alter routes or facts.

2. :func:`run_assist` takes the resolved :class:`~app.models.schemas.DecisionResult`
   and either phrases it with the static templates (no question) or forwards
   the grounded facts plus the sanitized question to the LLM layer for
   natural-language rephrasing. The LLM can only *phrase* pre-resolved facts.

Crowd-avoidance logic:
    When the nearest facility for a given intent is at high crowd level,
    :func:`_maybe_swap_for_crowd` scans the remaining candidates for a
    quieter alternative (not high crowd) that is still reasonably close.
    The swap is deterministic and reproducible: candidates are sorted by
    crowd index ascending, then by distance, then by facility ID.

Typical usage::

    from app.services.context_engine import run_assist, build_decision
    from app.services.stadium_data import get_stadium
    from app.services.llm import MockLLM

    stadium = get_stadium()
    decision = build_decision(ctx, stadium)
    response = await run_assist(ctx, stadium, MockLLM())
"""

from __future__ import annotations

from app.models.schemas import (
    AccessibilityMode,
    AccessibilityNeed,
    AssistResponse,
    CrowdLevel,
    DecisionResult,
    DestinationIntent,
    FacilityInfo,
    RouteStep,
    UserContext,
)
from app.services import phrasing
from app.services.crowd import effective_crowd
from app.services.llm import LLMClient
from app.services.phrasing import PhrasingContext
from app.services.routing import find_path, path_distance
from app.services.stadium_data import Edge, Facility, Stadium, localized
from app.utils.constants import KICKOFF_URGENCY_MINUTES

# ---------------------------------------------------------------------------
# Intent → facility-type mapping
# ---------------------------------------------------------------------------

# Maps each destination intent to the set of facility types that satisfy it.
# Used by _candidates_with_routes to query the stadium for matching facilities.
_INTENT_TO_TYPES: dict[DestinationIntent, set[str]] = {
    DestinationIntent.restroom: {"restroom", "accessible_restroom"},
    DestinationIntent.first_aid: {"first_aid"},
    DestinationIntent.concession: {"concession"},
    DestinationIntent.guest_services: {"guest_services"},
    DestinationIntent.water: {"water"},
    DestinationIntent.sensory_room: {"sensory_room"},
    DestinationIntent.exit: {"exit"},
    DestinationIntent.gate: {"gate"},
    # ``seat`` is resolved specially from the ticket section number, not by type.
}

# Intents where swapping to a quieter equivalent facility is appropriate.
# Excludes ``seat`` (location is fixed by ticket) and ``first_aid`` (never
# reroute an emergency for crowd congestion reasons).
_SWAP_ELIGIBLE: set[DestinationIntent] = {
    DestinationIntent.restroom,
    DestinationIntent.concession,
    DestinationIntent.water,
    DestinationIntent.guest_services,
    DestinationIntent.sensory_room,
    DestinationIntent.gate,
    DestinationIntent.exit,
}

# Numeric index of each crowd level — used for sorting alternatives by quietness.
_CROWD_INDEX: dict[CrowdLevel, int] = {
    CrowdLevel.low: 0,
    CrowdLevel.medium: 1,
    CrowdLevel.high: 2,
}

# Intents for which nearness to kickoff generates an urgency banner.
_HURRY_INTENTS: set[DestinationIntent] = {DestinationIntent.gate, DestinationIntent.seat}


class RouteNotFound(Exception):
    """Raised when no facility or route satisfies the request under its constraints.

    This is a domain-level exception (not an HTTP error), caught by the
    FastAPI exception handler in :mod:`app.main` and converted to a 404 response.

    Examples of conditions that raise this:
        - No reachable facility exists for the requested intent and accessibility mode.
        - The seat fixture is missing from the data file.
        - No step-free path exists to the requested facility.
    """


def _to_facility_info(facility: Facility, language: str) -> FacilityInfo:
    """Convert a raw :class:`~app.services.stadium_data.Facility` to the public API model.

    Resolves localized ``name`` and ``landmark`` strings for the requested
    language using :func:`~app.services.stadium_data.localized` and wraps
    them in the :class:`~app.models.schemas.FacilityInfo` response schema.

    Args:
        facility: The internal :class:`~app.services.stadium_data.Facility`
            dataclass loaded from the JSON fixtures.
        language: ISO 639-1 language code for name and landmark resolution.

    Returns:
        A :class:`~app.models.schemas.FacilityInfo` instance with all
        localized fields resolved for the requested language.
    """
    return FacilityInfo(
        id=facility.id,
        name=localized(facility.names, language) or facility.id,
        type=facility.type,
        zone=facility.zone,
        accessible=facility.accessible,
        landmark=localized(facility.landmarks, language),
    )


def _resolve_seat(ctx: UserContext, stadium: Stadium) -> Facility:
    """Select the seat facility implied by the fan's ticket section number.

    Ticket sections starting with ``'2'``, ``'3'``, or ``'4'`` map to the
    upper bowl (300-level); all others (including empty) map to the lower
    bowl (100-level). This mirrors MetLife Stadium's physical numbering.

    Args:
        ctx: The validated fan request context containing the optional
            ``ticket_section`` field.
        stadium: The loaded :class:`~app.services.stadium_data.Stadium`
            instance used to look up the seat facility by ID.

    Returns:
        The :class:`~app.services.stadium_data.Facility` for either
        ``"seat_upper"`` or ``"seat_lower"`` depending on the ticket section.

    Raises:
        RouteNotFound: If neither ``"seat_upper"`` nor ``"seat_lower"`` is
            present in the stadium fixtures (indicates a data integrity issue).
    """
    section = (ctx.ticket_section or "").strip()
    # Sections starting with 2/3/4 are upper bowl at MetLife (300-level stands).
    upper = bool(section) and section[0] in {"2", "3", "4"}
    target_id = "seat_upper" if upper else "seat_lower"
    for facility in stadium.facilities:
        if facility.id == target_id:
            return facility
    raise RouteNotFound("seat facility fixture missing")


def _candidates_with_routes(
    ctx: UserContext,
    stadium: Stadium,
    types: set[str],
    *,
    accessible_only: bool,
    step_free: bool,
) -> list[tuple[Facility, list[Edge], int]]:
    """Find all reachable facilities of the given types with their routes and distances.

    Iterates over every facility matching ``types`` (filtered by accessibility
    when required) and runs Dijkstra pathfinding from the fan's current zone
    to each candidate's zone. Unreachable candidates are silently excluded.

    Results are sorted deterministically: nearest first, then alphabetically
    by facility ID to break ties, ensuring the same input always produces
    the same facility selection.

    Args:
        ctx: The validated fan request context providing ``current_location``
            and accessibility information.
        stadium: The loaded :class:`~app.services.stadium_data.Stadium`
            instance providing the graph and facility list.
        types: Set of facility type strings to match against.
        accessible_only: If ``True``, only ``accessible=True`` facilities are
            included in the candidate list.
        step_free: If ``True``, Dijkstra excludes stair edges to produce
            wheelchair-accessible routes.

    Returns:
        A list of ``(facility, path_edges, total_distance)`` tuples for all
        reachable matching facilities, sorted nearest-first then by ID.
    """
    results: list[tuple[Facility, list[Edge], int]] = []
    for facility in stadium.facilities_of_types(types, accessible_only=accessible_only):
        path = find_path(stadium, ctx.current_location, facility.zone, step_free_only=step_free)
        if path is None:
            continue
        results.append((facility, path, path_distance(path)))
    # Deterministic ordering: nearest first, then by ID for tie-breaking.
    results.sort(key=lambda item: (item[2], item[0].id))
    return results


def _build_route_steps(
    stadium: Stadium,
    start: str,
    path: list[Edge],
    facility: Facility,
    language: str,
) -> list[RouteStep]:
    """Convert a list of graph edges into localized, accessibility-aware route steps.

    Each edge becomes one :class:`~app.models.schemas.RouteStep` with a
    localized instruction sentence. The final step includes the facility name
    and landmark (if defined) to orient the fan at their destination.

    Args:
        stadium: The loaded :class:`~app.services.stadium_data.Stadium`
            instance used to resolve zone display names.
        start: Zone ID of the fan's current location (the starting node).
        path: Ordered list of :class:`~app.services.stadium_data.Edge`
            objects from ``start`` to the facility's zone.
        facility: The resolved target :class:`~app.services.stadium_data.Facility`.
        language: ISO 639-1 language code for all localized strings.

    Returns:
        An ordered list of :class:`~app.models.schemas.RouteStep` instances
        ready for inclusion in the API response.
    """
    steps: list[RouteStep] = []
    facility_name = localized(facility.names, language) or facility.id
    node = start
    for i, edge in enumerate(path):
        is_final = i == len(path) - 1
        # Include the landmark description only on the final step so the
        # fan knows exactly where to look when they arrive at the destination.
        landmark = localized(facility.landmarks, language) if is_final else None
        steps.append(
            RouteStep(
                order=i + 1,
                from_zone=node,
                to_zone=edge.to,
                means=edge.means,
                step_free=edge.step_free,
                distance=edge.distance,
                landmark=landmark,
                instruction=phrasing.step_instruction(
                    edge.means,
                    stadium.zone_name(edge.to, language),
                    landmark,
                    is_final=is_final,
                    facility_name=facility_name,
                    language=language,
                ),
            )
        )
        node = edge.to
    return steps


def _maybe_swap_for_crowd(
    ctx: UserContext,
    stadium: Stadium,
    facility: Facility,
    path: list[Edge],
    candidates: list[tuple[Facility, list[Edge], int]],
) -> tuple[Facility, list[Edge], str | None]:
    """Swap to a quieter facility if the primary selection is at high crowd level.

    Implements the crowd-avoidance rerouting logic: if the nearest eligible
    facility has ``CrowdLevel.high`` congestion, this function searches the
    remaining candidates for a non-high-crowd alternative. The quietest
    alternative is preferred, with ties broken by distance then facility ID
    to ensure deterministic output.

    Swap eligibility is governed by :data:`_SWAP_ELIGIBLE` — emergency intents
    (``first_aid``) and fixed intents (``seat``) are never rerouted for crowd.

    Args:
        ctx: The validated fan request context (used for intent and timing).
        stadium: The loaded :class:`~app.services.stadium_data.Stadium`
            instance for crowd queries.
        facility: The primary (nearest) candidate facility selected before
            crowd checking.
        path: The Dijkstra path to ``facility``.
        candidates: All reachable candidates for this intent, sorted by
            distance, as returned by :func:`_candidates_with_routes`.

    Returns:
        A three-tuple ``(selected_facility, selected_path, alternatives_note)``
        where ``alternatives_note`` is a localized explanation string if a
        swap occurred, or ``None`` if the primary facility was kept.
    """
    # Only swap-eligible intents can be rerouted for crowd reasons.
    if ctx.destination_intent not in _SWAP_ELIGIBLE:
        return facility, path, None

    primary_crowd = CrowdLevel(effective_crowd(stadium, facility.zone, ctx.minutes_to_kickoff))
    if primary_crowd != CrowdLevel.high:
        # Primary facility is not at high crowd — no swap needed.
        return facility, path, None

    # Collect non-high-crowd alternatives, scored by (crowd_index, distance, id).
    alternatives: list[tuple[int, int, str, Facility, list[Edge]]] = []
    for cand, cand_path, cand_dist in candidates:
        if cand.id == facility.id:
            continue
        cand_crowd = CrowdLevel(effective_crowd(stadium, cand.zone, ctx.minutes_to_kickoff))
        if cand_crowd == CrowdLevel.high:
            # This alternative is also high — skip it.
            continue
        alternatives.append((_CROWD_INDEX[cand_crowd], cand_dist, cand.id, cand, cand_path))

    if not alternatives:
        # All alternatives are also high — keep the nearest facility.
        return facility, path, None

    # Sort: quietest first (crowd_index ASC), then nearest (dist ASC), then id (alpha).
    alternatives.sort(key=lambda a: (a[0], a[1], a[2]))
    _, _, _, alt_facility, alt_path = alternatives[0]
    note = phrasing.alternatives_note(alt_facility.type, ctx.language.value)
    return alt_facility, alt_path, note


def build_decision(ctx: UserContext, stadium: Stadium) -> DecisionResult:
    """Run the deterministic rules pipeline and return a structured decision.

    Resolves all routing facts from the structured ``ctx`` without any LLM
    involvement. The pipeline:
    1. Derives accessibility flags (step-free routing, accessible facilities,
       response mode) from the declared ``accessibility_needs``.
    2. Resolves the target facility — either by seat-bowl inference (``seat``
       intent) or by proximity-ranked facility matching (all other intents).
    3. Applies crowd-avoidance rerouting if the primary facility is congested.
    4. Computes the crowd level at the final target zone.
    5. Evaluates urgency (kickoff imminent + time-sensitive intent).
    6. Builds the ordered list of localized route steps.

    Args:
        ctx: The validated :class:`~app.models.schemas.UserContext` from the
            fan's API request.
        stadium: The loaded :class:`~app.services.stadium_data.Stadium`
            instance providing zones, facilities, and crowd data.

    Returns:
        A :class:`~app.models.schemas.DecisionResult` containing all resolved
        facts ready for phrasing by :func:`run_assist`.

    Raises:
        RouteNotFound: If no reachable facility exists for the requested intent
            under the given accessibility constraints, or if the seat fixture
            is missing from the data.
    """
    needs = set(ctx.accessibility_needs)
    wheelchair = AccessibilityNeed.wheelchair in needs
    visual = AccessibilityNeed.visual in needs
    hearing = AccessibilityNeed.hearing in needs

    # Wheelchair OR visual users get accessible-only facilities and step-free routes.
    # Visual users additionally get landmark-based, screen-reader-optimized instructions.
    accessible_only = wheelchair or visual
    step_free = wheelchair or visual

    # Select response mode based on declared accessibility needs (priority: visual > hearing).
    if visual:
        mode = AccessibilityMode.screen_reader
    elif hearing:
        mode = AccessibilityMode.captioned
    else:
        mode = AccessibilityMode.standard

    # --- Facility + route resolution ---
    if ctx.destination_intent == DestinationIntent.seat:
        # Seat intent: resolved from ticket section, not by proximity search.
        facility = _resolve_seat(ctx, stadium)
        path = find_path(stadium, ctx.current_location, facility.zone, step_free_only=step_free)
        if path is None:
            raise RouteNotFound("no accessible route to seat")
        alternatives_note: str | None = None
    else:
        types = _INTENT_TO_TYPES[ctx.destination_intent]
        candidates = _candidates_with_routes(
            ctx, stadium, types, accessible_only=accessible_only, step_free=step_free
        )
        if not candidates:
            raise RouteNotFound(f"no reachable facility for intent {ctx.destination_intent.value}")
        facility, path, _dist = candidates[0]
        # Crowd-avoidance: swap to a quieter alternative if the nearest is at high crowd.
        facility, path, alternatives_note = _maybe_swap_for_crowd(
            ctx, stadium, facility, path, candidates
        )

    # --- Crowd level at the final selected facility zone ---
    crowd_level = CrowdLevel(effective_crowd(stadium, facility.zone, ctx.minutes_to_kickoff))

    # --- Urgency: kickoff imminent and destination is time-sensitive ---
    hurry = ctx.minutes_to_kickoff < KICKOFF_URGENCY_MINUTES and ctx.destination_intent in _HURRY_INTENTS
    urgency = phrasing.urgency_note(ctx.language.value) if hurry else None

    route_steps = _build_route_steps(stadium, ctx.current_location, path, facility, ctx.language.value)

    return DecisionResult(
        facility=_to_facility_info(facility, ctx.language.value),
        route_steps=route_steps,
        crowd_level=crowd_level,
        language=ctx.language,
        accessibility_mode=mode,
        landmark_based=visual,
        hurry=hurry,
        alternatives_note=alternatives_note,
        urgency=urgency,
    )


async def run_assist(ctx: UserContext, stadium: Stadium, llm: LLMClient) -> AssistResponse:
    """Orchestrate the full request pipeline: rules engine then optional LLM phrasing.

    Delegates all fact resolution to :func:`build_decision` (deterministic,
    LLM-free), then either phrases the result with static templates (when no
    free-text question is provided) or forwards the grounded facts plus the
    sanitized question to the LLM for natural-language rephrasing.

    This architecture ensures the LLM can only *phrase* pre-resolved facts
    and cannot invent facilities, alter routes, or change crowd data regardless
    of what is written in the fan's free-text question.

    Args:
        ctx: The validated :class:`~app.models.schemas.UserContext` from the
            fan's API request.
        stadium: The loaded :class:`~app.services.stadium_data.Stadium`
            instance providing zones, facilities, and crowd data.
        llm: The active :class:`~app.services.llm.LLMClient` instance —
            either :class:`~app.services.llm.GeminiClient` or
            :class:`~app.services.llm.MockLLM`.

    Returns:
        A fully populated :class:`~app.models.schemas.AssistResponse` ready
        to be serialized and returned to the client.

    Raises:
        RouteNotFound: Propagated from :func:`build_decision` when no
            reachable facility exists for the request constraints.
    """
    decision = build_decision(ctx, stadium)

    phrasing_ctx = PhrasingContext(
        language=decision.language.value,
        facility_name=decision.facility.name,
        facility_type=decision.facility.type,
        facility_landmark=decision.facility.landmark,
        crowd_level=decision.crowd_level.value,
        accessibility_mode=decision.accessibility_mode.value,
        landmark_based=decision.landmark_based,
        hurry=decision.hurry,
        alternative_type=decision.facility.type if decision.alternatives_note else None,
        total_distance=sum(step.distance for step in decision.route_steps),
        step_count=len(decision.route_steps),
    )

    if ctx.question:
        # Free-text question present — engage the LLM layer for phrasing/translation.
        # The question is sandwiched between VERIFIED_FACTS and prompt delimiters
        # so the model is explicitly instructed to treat it as data only.
        answer = await llm.phrase(phrasing_ctx, ctx.question)
        used_llm = llm.is_live
    else:
        # No question — short-circuit to static templates; skip the LLM entirely.
        answer = phrasing.render_answer(phrasing_ctx)
        used_llm = False

    return AssistResponse(
        answer=answer,
        route_steps=decision.route_steps,
        facility=decision.facility,
        crowd_level=decision.crowd_level,
        language=decision.language,
        accessibility_mode=decision.accessibility_mode,
        alternatives_note=decision.alternatives_note,
        urgency=decision.urgency,
        used_llm=used_llm,
    )
