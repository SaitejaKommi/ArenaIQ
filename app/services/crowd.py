"""
ArenaIQ — Time-based crowd congestion simulation.

This module simulates crowd density at stadium zones as a function of
``minutes_to_kickoff`` using a two-phase bump/relief model:

Phase 1 — Pre-match surge
    For zone types that experience crowding (e.g. ``gate``, ``concourse``),
    the base crowd level is bumped upward in two pre-kickoff time windows:

    - **Imminent window** (0 to ``KICKOFF_IMMINENT_MINUTES`` minutes before
      kickoff): crowd index raised by ``CROWD_BUMP_IMMINENT`` (typically +2).
    - **Pre-match window** (``KICKOFF_IMMINENT_MINUTES`` to
      ``KICKOFF_PRE_MATCH_MINUTES`` minutes before kickoff): crowd index
      raised by ``CROWD_BUMP_PRE_MATCH`` (typically +1).

Phase 2 — In-play relief
    Once the match has started (``minutes_to_kickoff < 0``), gate zones
    experience a relief bump (``-CROWD_RELIEF_IN_PLAY``) as fans settle
    into their seats and stop arriving.

The base level for each zone is loaded from the ``crowd.json`` fixture and
indexed as ``'low'``, ``'medium'``, or ``'high'``. After bumps are applied,
the result is clamped back into the valid range using :func:`_clamp`.

Constants used (from :mod:`app.utils.constants`):
    - ``KICKOFF_IMMINENT_MINUTES``
    - ``KICKOFF_PRE_MATCH_MINUTES``
    - ``CROWD_BUMP_IMMINENT``
    - ``CROWD_BUMP_PRE_MATCH``
    - ``CROWD_RELIEF_IN_PLAY``

Typical usage
-------------
The :mod:`~app.services.context_engine` calls :func:`effective_crowd` to
determine whether the recommended facility is congested and whether to
trigger a crowd-swap to a quieter alternative::

    from app.services.crowd import effective_crowd

    level = effective_crowd(stadium, "gate_a", minutes_to_kickoff=5)
    # "high" — gates surge to high 5 minutes before kickoff
"""


from __future__ import annotations

from typing import Any

from app.services.stadium_data import Stadium
from app.utils.constants import (
    CROWD_BUMP_IMMINENT,
    CROWD_BUMP_PRE_MATCH,
    CROWD_RELIEF_IN_PLAY,
    KICKOFF_IMMINENT_MINUTES,
    KICKOFF_PRE_MATCH_MINUTES,
)

_LEVELS: tuple[str, ...] = ("low", "medium", "high")
_LEVEL_INDEX: dict[str, int] = {level: i for i, level in enumerate(_LEVELS)}


def _clamp(index: int) -> str:
    """Clamp a crowd-level index to the valid range.

    Args:
        index: Computed integer crowd index.

    Returns:
        One of 'low', 'medium', or 'high'.

    Raises:
        None

    Example:
        >>> _clamp(5)
        'high'
    """
    return _LEVELS[max(0, min(len(_LEVELS) - 1, index))]


def _calculate_surge(
    zone_type: str, surge_types: set[str], minutes_to_kickoff: int, sim: dict[str, Any]
) -> int:
    """Calculate the positive crowd index surge for pre-kickoff windows.

    Args:
        zone_type: The category of the zone (e.g. 'gate').
        surge_types: Set of zone types that experience surging.
        minutes_to_kickoff: Minutes until kickoff.
        sim: Simulation config dictionary from the stadium fixture.

    Returns:
        Integer crowd bump (0, 1, or 2).

    Raises:
        None

    Example:
        >>> _calculate_surge("gate", {"gate"}, 5, {})
        2
    """
    if zone_type not in surge_types:
        return 0
    pre: int = int(sim.get("pre_match_window_minutes", KICKOFF_PRE_MATCH_MINUTES))
    imminent: int = int(sim.get("imminent_window_minutes", KICKOFF_IMMINENT_MINUTES))
    if 0 <= minutes_to_kickoff <= imminent:
        return CROWD_BUMP_IMMINENT
    if imminent < minutes_to_kickoff <= pre:
        return CROWD_BUMP_PRE_MATCH
    return 0


def _calculate_relief(
    zone_type: str, minutes_to_kickoff: int, sim: dict[str, Any]
) -> int:
    """Calculate the negative crowd relief once the match is underway.

    Args:
        zone_type: The category of the zone.
        minutes_to_kickoff: Minutes until kickoff (negative if in-play).
        sim: Simulation config dictionary.

    Returns:
        Integer crowd drop (0 or negative).

    Raises:
        None

    Example:
        >>> _calculate_relief("gate", -5, {"in_play_gate_relief": True})
        -1
    """
    if minutes_to_kickoff < 0 and zone_type == "gate" and sim.get("in_play_gate_relief"):
        return -CROWD_RELIEF_IN_PLAY
    return 0


def effective_crowd(stadium: Stadium, zone_id: str, minutes_to_kickoff: int | None) -> str:
    """Return the simulated crowd level for a zone at the given time.

    Combines the static base crowd index with time-based surge and relief
    bumps calculated by helper functions.

    Args:
        stadium: The loaded stadium model.
        zone_id: Zone identifier string.
        minutes_to_kickoff: Mins to kickoff, or None for base level only.

    Returns:
        Crowd level string: 'low', 'medium', or 'high'.

    Raises:
        None

    Example:
        >>> level = effective_crowd(stadium, "gate_a", 5)
    """
    base_index: int = _LEVEL_INDEX.get(stadium.base_crowd(zone_id), 0)
    if minutes_to_kickoff is None:
        return _clamp(base_index)

    sim: dict[str, Any] = stadium.crowd_sim
    surge_types: set[str] = set(sim.get("surge_zone_types", []))
    zone_type: str = stadium.zone_type(zone_id)

    bump: int = 0
    bump += _calculate_surge(zone_type, surge_types, minutes_to_kickoff, sim)
    bump += _calculate_relief(zone_type, minutes_to_kickoff, sim)

    return _clamp(base_index + bump)
