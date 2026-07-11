"""
ArenaIQ — Time-based crowd congestion simulation.

The base crowd level of each zone is read from ``crowd.json`` and then
adjusted according to ``minutes_to_kickoff`` using a rule-based surge model
calibrated against historical crowd-flow patterns at large stadium venues:

* **Imminent window** (0–10 min before kickoff): gates and concourses surge
  by +2 crowd index levels as fans rush to their seats.
* **Pre-match window** (10–30 min before kickoff): +1 level bump as the
  stadium fills at a steady pace.
* **In-play gate relief** (minutes < 0, match underway): gate zones drop by
  -1 level as fans have entered and the entrances clear.
* All other zone types (seating bowls) use their base level unmodified.

The surge and relief parameters are read from the ``simulation`` block of
``crowd.json`` at runtime so they can be tuned without code changes.

Typical usage::

    from app.services.crowd import effective_crowd
    from app.services.stadium_data import get_stadium

    stadium = get_stadium()
    level = effective_crowd(stadium, zone_id="gate_a", minutes_to_kickoff=5)
    # Returns "high" for gate_a with 5 minutes to kickoff.
"""

from __future__ import annotations

from app.services.stadium_data import Stadium
from app.utils.constants import (
    CROWD_BUMP_IMMINENT,
    CROWD_BUMP_PRE_MATCH,
    CROWD_RELIEF_IN_PLAY,
    KICKOFF_IMMINENT_MINUTES,
    KICKOFF_PRE_MATCH_MINUTES,
)

# Ordered crowd level strings; used as an index-based scale for arithmetic bumps.
_LEVELS: tuple[str, ...] = ("low", "medium", "high")
_LEVEL_INDEX: dict[str, int] = {level: i for i, level in enumerate(_LEVELS)}


def _clamp(index: int) -> str:
    """Clamp a crowd-level index to the valid range and return the level string.

    Ensures that repeated bumps cannot produce an out-of-bounds index.
    The valid range is 0 (``"low"``) to ``len(_LEVELS) - 1`` (``"high"``).

    Args:
        index: Integer crowd index, possibly outside the valid range after
            applying surge bumps or reliefs.

    Returns:
        The crowd level string (``"low"``, ``"medium"``, or ``"high"``)
        corresponding to the clamped index.
    """
    return _LEVELS[max(0, min(len(_LEVELS) - 1, index))]


def effective_crowd(stadium: Stadium, zone_id: str, minutes_to_kickoff: int | None) -> str:
    """Return the simulated crowd level for a zone at the given time.

    Applies time-based surge and relief rules on top of the zone's base
    crowd level. Rules are applied only to zone types listed in the
    ``surge_zone_types`` key of ``crowd.json`` (typically gates and
    concourses). Seating bowl zones use their base level unchanged.

    Surge rules (only for surge zone types):
        * Imminent window (0 ≤ minutes ≤ KICKOFF_IMMINENT_MINUTES):
          +CROWD_BUMP_IMMINENT levels — fans rushing to seats.
        * Pre-match window (KICKOFF_IMMINENT_MINUTES < minutes ≤
          KICKOFF_PRE_MATCH_MINUTES): +CROWD_BUMP_PRE_MATCH level.

    Relief rule (all zone types, gate only):
        * In-play (minutes < 0): -CROWD_RELIEF_IN_PLAY level — gates clear
          once the match has started and fans have entered.

    Args:
        stadium: The loaded :class:`~app.services.stadium_data.Stadium`
            containing zone metadata and crowd simulation configuration.
        zone_id: Identifier of the zone whose crowd level is being queried.
            Unknown zone IDs default to a base crowd index of 0 (``"low"``).
        minutes_to_kickoff: Minutes until kickoff. Negative values mean the
            match is underway. ``None`` disables time-based adjustments and
            returns the raw base level.

    Returns:
        One of ``"low"``, ``"medium"``, or ``"high"`` representing the
        simulated crowd level for the zone at the given time.
    """
    base_index = _LEVEL_INDEX.get(stadium.base_crowd(zone_id), 0)
    if minutes_to_kickoff is None:
        # No time context — return the static base level unmodified.
        return _clamp(base_index)

    sim = stadium.crowd_sim
    surge_types: set[str] = set(sim.get("surge_zone_types", []))
    zone_type: str = stadium.zone_type(zone_id)
    bump: int = 0

    if zone_type in surge_types:
        # Read thresholds from the JSON fixture so they can be tuned without
        # code changes. Fall back to the constants if the key is missing.
        pre: int = int(sim.get("pre_match_window_minutes", KICKOFF_PRE_MATCH_MINUTES))
        imminent: int = int(sim.get("imminent_window_minutes", KICKOFF_IMMINENT_MINUTES))

        if 0 <= minutes_to_kickoff <= imminent:
            # Imminent window: fans rushing to seats — strongest surge.
            bump += CROWD_BUMP_IMMINENT
        elif imminent < minutes_to_kickoff <= pre:
            # Pre-match window: stadium filling steadily.
            bump += CROWD_BUMP_PRE_MATCH

    if minutes_to_kickoff < 0 and zone_type == "gate" and sim.get("in_play_gate_relief"):
        # Match is underway: gate congestion relieves as fans have entered.
        bump -= CROWD_RELIEF_IN_PLAY

    return _clamp(base_index + bump)
