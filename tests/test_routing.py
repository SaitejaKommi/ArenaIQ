"""Routing tests — shortest path, unknown/disconnected nodes, step-free constraint."""

from __future__ import annotations

from app.services.routing import find_path, path_distance
from app.services.stadium_data import Stadium, Zone, get_stadium


def test_same_start_and_goal_is_empty_path():
    assert find_path(get_stadium(), "gate_a", "gate_a") == []


def test_unknown_zone_returns_none():
    assert find_path(get_stadium(), "nowhere", "gate_a") is None


def test_disconnected_goal_returns_none():
    stadium = Stadium(
        name="t", fifa_name="t", city="t", capacity=1,
        zones={
            "a": Zone("a", {"en": "A"}, "concourse", "x"),
            "b": Zone("b", {"en": "B"}, "concourse", "x"),
        },
        adjacency={"a": [], "b": []},
        facilities=[], crowd_base={}, crowd_sim={},
    )
    assert find_path(stadium, "a", "b") is None


def test_step_free_route_avoids_stairs_and_is_longer():
    stadium = get_stadium()
    default = find_path(stadium, "concourse_lower_sw", "concourse_upper_w")
    step_free = find_path(stadium, "concourse_lower_sw", "concourse_upper_w", step_free_only=True)
    assert any(edge.means == "stairs" for edge in default)
    assert step_free is not None and all(edge.step_free for edge in step_free)
    assert path_distance(step_free) > path_distance(default)
