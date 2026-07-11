"""Crowd-simulation tests — deterministic escalation/relief from kick-off time."""

from __future__ import annotations

from app.services.crowd import effective_crowd
from app.services.stadium_data import get_stadium


def test_none_minutes_returns_base_level():
    stadium = get_stadium()
    # concourse_lower_sw base level is "high".
    assert effective_crowd(stadium, "concourse_lower_sw", None) == "high"


def test_in_play_gate_relief():
    stadium = get_stadium()
    # gate_a base "medium"; once the match is underway gates relax by one level.
    assert effective_crowd(stadium, "gate_a", -10) == "low"


def test_surge_windows_escalate_gates():
    stadium = get_stadium()
    # gate_c base "low": imminent (+2) → high, pre-match (+1) → medium.
    assert effective_crowd(stadium, "gate_c", 5) == "high"
    assert effective_crowd(stadium, "gate_c", 20) == "medium"
    # Well before kickoff → unchanged.
    assert effective_crowd(stadium, "gate_c", 300) == "low"
