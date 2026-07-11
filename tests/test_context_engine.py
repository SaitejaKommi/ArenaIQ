"""Rules-engine tests — deterministic decisions, no network (MockLLM not needed)."""

from __future__ import annotations

import pytest

from app.models.schemas import (
    AccessibilityMode,
    CrowdLevel,
    UserContext,
)
from app.services.context_engine import RouteNotFound, build_decision
from app.services.stadium_data import Facility, Stadium, Zone, get_stadium


def _mini_stadium(facilities: list[Facility]) -> Stadium:
    """A one-zone stadium with no edges — used to exercise defensive guards."""
    return Stadium(
        name="t", fifa_name="t", city="t", capacity=1,
        zones={"z1": Zone("z1", {"en": "Z1"}, "concourse", "x")},
        adjacency={"z1": []},
        facilities=facilities,
        crowd_base={"z1": "low"},
        crowd_sim={},
    )


def _ctx(**overrides) -> UserContext:
    base = {
        "language": "en",
        "current_location": "gate_a",  # valid real zone id (passes validation)
        "destination_intent": "restroom",
        "minutes_to_kickoff": 60,
    }
    base.update(overrides)
    return UserContext(**base)


def _decide(**overrides):
    base = {
        "language": "en",
        "current_location": "concourse_lower_sw",
        "destination_intent": "restroom",
        "minutes_to_kickoff": 60,
    }
    base.update(overrides)
    return build_decision(UserContext(**base), get_stadium())


def test_wheelchair_gets_accessible_facility_and_step_free_route():
    decision = _decide(accessibility_needs=["wheelchair"])
    assert decision.facility.accessible is True
    assert decision.route_steps, "expected a multi-step route"
    assert all(step.step_free for step in decision.route_steps)


def test_visual_need_sets_landmark_and_screen_reader_mode():
    decision = _decide(accessibility_needs=["visual"])
    assert decision.landmark_based is True
    assert decision.accessibility_mode is AccessibilityMode.screen_reader
    assert decision.facility.accessible is True
    # Final step carries a landmark for audio-friendly directions.
    assert decision.route_steps[-1].landmark


def test_hearing_need_sets_captioned_mode():
    decision = _decide(accessibility_needs=["hearing"])
    assert decision.accessibility_mode is AccessibilityMode.captioned


def test_imminent_kickoff_triggers_urgency_for_gate():
    hurried = _decide(destination_intent="gate", current_location="concourse_upper_w",
                      minutes_to_kickoff=10)
    assert hurried.hurry is True
    assert hurried.urgency is not None

    relaxed = _decide(destination_intent="gate", current_location="concourse_upper_w",
                      minutes_to_kickoff=90)
    assert relaxed.hurry is False
    assert relaxed.urgency is None


def test_high_crowd_suggests_quieter_alternative():
    # The South-West concourse concession is "high"; the engine should reroute.
    decision = _decide(destination_intent="concession", current_location="concourse_lower_sw",
                       minutes_to_kickoff=120)
    assert decision.alternatives_note is not None
    assert decision.crowd_level is not CrowdLevel.high
    assert decision.facility.id != "concession_sw"


def test_first_aid_intent_never_swaps_for_crowd():
    # first aid is excluded from crowd-based rerouting, even from a busy zone.
    decision = _decide(destination_intent="first_aid", current_location="concourse_lower_sw",
                       minutes_to_kickoff=5)
    assert decision.alternatives_note is None
    assert decision.facility.type == "first_aid"


def test_seat_resolved_from_ticket_section():
    lower = _decide(destination_intent="seat", ticket_section="134")
    assert lower.facility.id == "seat_lower"
    upper = _decide(destination_intent="seat", ticket_section="332")
    assert upper.facility.id == "seat_upper"


def test_missing_seat_fixture_raises_route_not_found():
    with pytest.raises(RouteNotFound):
        build_decision(_ctx(destination_intent="seat"), _mini_stadium([]))


def test_unreachable_seat_raises_route_not_found():
    seat = Facility("seat_lower", {"en": "Seat"}, "seat", "z1", True, None)
    with pytest.raises(RouteNotFound):
        build_decision(_ctx(destination_intent="seat"), _mini_stadium([seat]))


def test_no_reachable_facility_raises_route_not_found():
    # Facility exists but its zone is unreachable from the start → guarded 404.
    restroom = Facility("r1", {"en": "R"}, "restroom", "z1", False, None)
    with pytest.raises(RouteNotFound):
        build_decision(_ctx(destination_intent="restroom"), _mini_stadium([restroom]))


def test_default_route_may_use_stairs_but_accessible_route_never_does():
    # Non-accessible request to an upper-level restroom can take the stairs...
    default = _decide(destination_intent="restroom", current_location="concourse_lower_sw")
    # ...while the wheelchair request avoids them entirely.
    accessible = _decide(destination_intent="restroom",
                         current_location="concourse_lower_sw",
                         accessibility_needs=["wheelchair"])
    assert all(step.step_free for step in accessible.route_steps)
    assert default.facility.id != accessible.facility.id
