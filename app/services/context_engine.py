"""
ArenaIQ — Context-driven decision engine.

# ============================================================
# ARCHITECTURAL DECISION: RULES-FIRST, LLM-LAST
# ============================================================
# All navigation decisions (facility selection, pathfinding,
# crowd rerouting, accessibility constraints, urgency detection)
# are resolved deterministically inside this module BEFORE any
# call to the language model is made.
#
# The LLM receives only pre-verified facts and is instructed to
# phrase them into natural language. This eliminates hallucination
# risk entirely — the LLM cannot invent routes, facilities, or
# crowd levels because it never makes those decisions.
#
# This pattern is sometimes called "constrained generation" or
# "fact-grounded NLG" in the literature.
# ============================================================
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

_INTENT_TO_TYPES: dict[DestinationIntent, set[str]] = {
    DestinationIntent.restroom: {"restroom", "accessible_restroom"},
    DestinationIntent.first_aid: {"first_aid"},
    DestinationIntent.concession: {"concession"},
    DestinationIntent.guest_services: {"guest_services"},
    DestinationIntent.water: {"water"},
    DestinationIntent.sensory_room: {"sensory_room"},
    DestinationIntent.exit: {"exit"},
    DestinationIntent.gate: {"gate"},
}

_SWAP_ELIGIBLE: set[DestinationIntent] = {
    DestinationIntent.restroom,
    DestinationIntent.concession,
    DestinationIntent.water,
    DestinationIntent.guest_services,
    DestinationIntent.sensory_room,
    DestinationIntent.gate,
    DestinationIntent.exit,
}

_CROWD_INDEX: dict[CrowdLevel, int] = {
    CrowdLevel.low: 0,
    CrowdLevel.medium: 1,
    CrowdLevel.high: 2,
}

_HURRY_INTENTS: set[DestinationIntent] = {DestinationIntent.gate, DestinationIntent.seat}


class RouteNotFound(Exception):
    """Raised when no facility or route satisfies the request constraints.

    Attributes:
        args: Standard Exception argument tuple.
    """


def _to_facility_info(facility: Facility, language: str) -> FacilityInfo:
    """Convert raw Facility to public schema.

    Args:
        facility: The stadium Facility instance.
        language: ISO 639-1 language code.

    Returns:
        A populated FacilityInfo schema.

    Raises:
        None

    Example:
        >>> info = _to_facility_info(fac, "en")
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
    """Select the seat facility implied by ticket section.

    Args:
        ctx: User request context.
        stadium: The loaded stadium model.

    Returns:
        The matched seat Facility.

    Raises:
        RouteNotFound: If the seat facility is missing from fixtures.

    Example:
        >>> fac = _resolve_seat(ctx, stadium)
    """
    section: str = (ctx.ticket_section or "").strip()
    target_id: str = "seat_upper" if section and section[0] in {"2", "3", "4"} else "seat_lower"
    for facility in stadium.facilities:
        if facility.id == target_id:
            return facility
    raise RouteNotFound("seat facility fixture missing")


def _find_candidate_paths(
    ctx: UserContext, stadium: Stadium, types: set[str], accessible_only: bool, step_free: bool
) -> list[tuple[Facility, list[Edge], int]]:
    """Iterate facilities and run Dijkstra for reachable candidates.

    Args:
        ctx: User context.
        stadium: Stadium model.
        types: Allowed facility types.
        accessible_only: Flag for accessible facilities.
        step_free: Flag for wheelchair paths.

    Returns:
        List of tuples: (facility, path, distance).

    Raises:
        None

    Example:
        >>> cands = _find_candidate_paths(ctx, stadium, {"restroom"}, False, False)
        >>> # [(facility, [edge, ...], 120), ...]
    """
    results: list[tuple[Facility, list[Edge], int]] = []
    for facility in stadium.facilities_of_types(types, accessible_only=accessible_only):
        path = find_path(stadium, ctx.current_location, facility.zone, step_free_only=step_free)
        if path is not None:
            results.append((facility, path, path_distance(path)))
    return results


def _candidates_with_routes(
    ctx: UserContext, stadium: Stadium, types: set[str], accessible_only: bool, step_free: bool
) -> list[tuple[Facility, list[Edge], int]]:
    """Find and sort all reachable facilities of the given types.

    Args:
        ctx: User context.
        stadium: Stadium model.
        types: Set of facility type strings.
        accessible_only: True to exclude non-accessible facilities.
        step_free: True to exclude stair edges.

    Returns:
        Reachable candidates sorted by distance then ID.

    Raises:
        None

    Example:
        >>> cands = _candidates_with_routes(ctx, stadium, {"gate"}, False, False)
    """
    results = _find_candidate_paths(ctx, stadium, types, accessible_only, step_free)
    results.sort(key=lambda item: (item[2], item[0].id))
    return results


def _build_step(
    stadium: Stadium,
    edge: Edge,
    index: int,
    is_final: bool,
    facility: Facility,
    language: str,
    start_node: str,
) -> RouteStep:
    """Construct a single RouteStep schema.

    Args:
        stadium: Stadium model.
        edge: The traversal edge.
        index: Zero-indexed position in route.
        is_final: True if this is the last step.
        facility: The target facility.
        language: ISO 639-1 code.
        start_node: The zone ID we depart from.

    Returns:
        Populated RouteStep.

    Raises:
        None

    Example:
        >>> step = _build_step(stadium, edge, 0, True, facility, "en", "gate_a")
        >>> step.order
        1
    """
    lm: str | None = localized(facility.landmarks, language) if is_final else None
    fname: str = localized(facility.names, language) or facility.id
    instr: str = phrasing.step_instruction(
        edge.means, stadium.zone_name(edge.to, language), lm, is_final=is_final, facility_name=fname, language=language
    )
    return RouteStep(
        order=index + 1, from_zone=start_node, to_zone=edge.to, means=edge.means,
        step_free=edge.step_free, distance=edge.distance, landmark=lm, instruction=instr
    )


def _build_route_steps(
    stadium: Stadium, start: str, path: list[Edge], facility: Facility, language: str
) -> list[RouteStep]:
    """Convert edges into localized route steps.

    Args:
        stadium: Stadium model.
        start: Starting zone ID.
        path: List of Edges.
        facility: Target facility.
        language: Language code.

    Returns:
        Ordered RouteSteps.

    Raises:
        None

    Example:
        >>> steps = _build_route_steps(stadium, "gate_a", path, fac, "en")
    """
    steps: list[RouteStep] = []
    node: str = start
    for i, edge in enumerate(path):
        is_final: bool = i == len(path) - 1
        steps.append(_build_step(stadium, edge, i, is_final, facility, language, node))
        node = edge.to
    return steps


def _score_alternatives(
    stadium: Stadium,
    candidates: list[tuple[Facility, list[Edge], int]],
    ctx: UserContext,
    primary_id: str,
) -> list[tuple[int, int, str, Facility, list[Edge]]]:
    """Score quiet alternatives for swap logic.

    Args:
        stadium: Stadium model.
        candidates: Candidate facilities list.
        ctx: User context.
        primary_id: ID of the primary congested facility to ignore.

    Returns:
        List of tuples scored by (crowd_index, distance, id).

    Raises:
        None
    """
    alts: list[tuple[int, int, str, Facility, list[Edge]]] = []
    for cand, cand_path, cand_dist in candidates:
        if cand.id == primary_id:
            continue
        c_lvl = CrowdLevel(effective_crowd(stadium, cand.zone, ctx.minutes_to_kickoff))
        if c_lvl != CrowdLevel.high:
            alts.append((_CROWD_INDEX[c_lvl], cand_dist, cand.id, cand, cand_path))
    alts.sort(key=lambda a: (a[0], a[1], a[2]))
    return alts


def _maybe_swap_for_crowd(
    ctx: UserContext,
    stadium: Stadium,
    facility: Facility,
    path: list[Edge],
    candidates: list[tuple[Facility, list[Edge], int]],
) -> tuple[Facility, list[Edge], str | None]:
    """Swap to a quieter facility if the primary is congested.

    Args:
        ctx: User context.
        stadium: Stadium model.
        facility: Primary candidate.
        path: Primary route.
        candidates: All candidates.

    Returns:
        Tuple of (Facility, Route, Optional[Note]).

    Raises:
        None

    Example:
        >>> fac, path, note = _maybe_swap_for_crowd(ctx, stadium, fac, path, cands)
    """
    if ctx.destination_intent not in _SWAP_ELIGIBLE:
        return facility, path, None
    if CrowdLevel(effective_crowd(stadium, facility.zone, ctx.minutes_to_kickoff)) != CrowdLevel.high:
        return facility, path, None

    alts = _score_alternatives(stadium, candidates, ctx, facility.id)
    if not alts:
        return facility, path, None

    _, _, _, alt_fac, alt_path = alts[0]
    note: str = phrasing.alternatives_note(alt_fac.type, ctx.language.value)
    return alt_fac, alt_path, note


def _resolve_accessibility(ctx: UserContext) -> tuple[bool, bool, AccessibilityMode]:
    """Determine routing flags based on needs.

    Args:
        ctx: User context.

    Returns:
        Tuple of (accessible_only, step_free, accessibility_mode).

    Raises:
        None

    Example:
        >>> acc, free, mode = _resolve_accessibility(ctx)
    """
    needs: set[AccessibilityNeed] = set(ctx.accessibility_needs)
    wheelchair: bool = AccessibilityNeed.wheelchair in needs
    visual: bool = AccessibilityNeed.visual in needs
    hearing: bool = AccessibilityNeed.hearing in needs

    if visual:
        return True, True, AccessibilityMode.screen_reader
    if hearing:
        return wheelchair, wheelchair, AccessibilityMode.captioned
    return wheelchair, wheelchair, AccessibilityMode.standard


def _select_facility(
    ctx: UserContext, stadium: Stadium, acc: bool, free: bool
) -> tuple[Facility, list[Edge], str | None]:
    """Resolve the target facility and path.

    Args:
        ctx: User context.
        stadium: Stadium model.
        acc: Accessible only flag.
        free: Step free flag.

    Returns:
        Tuple of (Facility, Route, Optional[SwapNote]).

    Raises:
        RouteNotFound: If no facility matches.

    Example:
        >>> fac, path, note = _select_facility(ctx, stadium, False, False)
    """
    if ctx.destination_intent == DestinationIntent.seat:
        fac: Facility = _resolve_seat(ctx, stadium)
        path: list[Edge] | None = find_path(stadium, ctx.current_location, fac.zone, step_free_only=free)
        if path is None:
            raise RouteNotFound("no accessible route to seat")
        return fac, path, None

    cands = _candidates_with_routes(ctx, stadium, _INTENT_TO_TYPES[ctx.destination_intent], acc, free)
    if not cands:
        raise RouteNotFound("no reachable facility for intent")
    return _maybe_swap_for_crowd(ctx, stadium, cands[0][0], cands[0][1], cands)


def build_decision(ctx: UserContext, stadium: Stadium) -> DecisionResult:
    """Run deterministic rules to resolve all routing facts.

    Args:
        ctx: The validated user request context.
        stadium: The loaded stadium graph.

    Returns:
        DecisionResult containing all resolved facts.

    Raises:
        RouteNotFound: If no facility/route exists.

    Example:
        >>> decision = build_decision(ctx, stadium)
    """
    acc, free, mode = _resolve_accessibility(ctx)
    facility, path, alt_note = _select_facility(ctx, stadium, acc, free)

    lvl: CrowdLevel = CrowdLevel(effective_crowd(stadium, facility.zone, ctx.minutes_to_kickoff))
    hurry: bool = ctx.minutes_to_kickoff < KICKOFF_URGENCY_MINUTES and ctx.destination_intent in _HURRY_INTENTS
    urgency: str | None = phrasing.urgency_note(ctx.language.value) if hurry else None
    steps: list[RouteStep] = _build_route_steps(stadium, ctx.current_location, path, facility, ctx.language.value)

    return DecisionResult(
        facility=_to_facility_info(facility, ctx.language.value),
        route_steps=steps, crowd_level=lvl, language=ctx.language,
        accessibility_mode=mode, landmark_based=(mode == AccessibilityMode.screen_reader),
        hurry=hurry, alternatives_note=alt_note, urgency=urgency,
    )


def _build_phrasing_context(dec: DecisionResult) -> PhrasingContext:
    """Construct the read-only phrasing context from the decision.

    Args:
        dec: The resolved decision facts.

    Returns:
        Populated PhrasingContext.

    Raises:
        None
    """
    return PhrasingContext(
        language=dec.language.value, facility_name=dec.facility.name,
        facility_type=dec.facility.type, facility_landmark=dec.facility.landmark,
        crowd_level=dec.crowd_level.value, accessibility_mode=dec.accessibility_mode.value,
        landmark_based=dec.landmark_based, hurry=dec.hurry,
        alternative_type=dec.facility.type if dec.alternatives_note else None,
        total_distance=sum(step.distance for step in dec.route_steps), step_count=len(dec.route_steps),
    )


async def run_assist(ctx: UserContext, stadium: Stadium, llm: LLMClient) -> AssistResponse:
    """Orchestrate rules engine then LLM phrasing.

    Args:
        ctx: The validated user context.
        stadium: The loaded stadium model.
        llm: The active LLM client instance.

    Returns:
        A populated AssistResponse.

    Raises:
        RouteNotFound: If pathfinding fails.

    Example:
        >>> res = await run_assist(ctx, stadium, llm)
    """
    dec: DecisionResult = build_decision(ctx, stadium)
    p_ctx: PhrasingContext = _build_phrasing_context(dec)

    if ctx.question:
        ans: str = await llm.phrase(p_ctx, ctx.question)
    else:
        ans = phrasing.render_answer(p_ctx)

    return AssistResponse(
        answer=ans, route_steps=dec.route_steps, facility=dec.facility,
        crowd_level=dec.crowd_level, language=dec.language,
        accessibility_mode=dec.accessibility_mode, alternatives_note=dec.alternatives_note,
        urgency=dec.urgency, used_llm=llm.is_live if ctx.question else False,
    )
