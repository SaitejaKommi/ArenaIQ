"""
ArenaIQ — Static stadium data models and graph building.

Provides the in-memory representation of the stadium zones, facilities,
and the navigable edge graph used by the routing engine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.logging_conf import get_logger

logger = get_logger(__name__)
_DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Zone:
    """Represents a discrete physical area within the stadium.

    Attributes:
        id: Unique string identifier for the zone.
        names: Localized name dictionary (e.g. {"en": "Gate A"}).
        type: The category of the zone (e.g. "gate", "concourse").
        level: Integer floor level (0 is ground).
    """
    id: str
    names: dict[str, str]
    type: str
    level: int


@dataclass(frozen=True)
class Edge:
    """Represents a navigable path from one zone to another.

    Attributes:
        to: Destination zone ID.
        distance: Walking distance in metres.
        means: Means of transit (e.g. "walk", "stairs").
        step_free: True if the path is navigable by wheelchair.
    """
    to: str
    distance: int
    means: str
    step_free: bool


@dataclass(frozen=True)
class Facility:
    """Represents an amenity located within a specific zone.

    Attributes:
        id: Unique string identifier.
        names: Localized name dictionary.
        type: Category (e.g. "restroom", "first_aid").
        zone: The zone ID where this facility is physically located.
        accessible: True if the facility is ADA compliant.
        landmarks: Optional localized landmark description.
    """
    id: str
    names: dict[str, str]
    type: str
    zone: str
    accessible: bool
    landmarks: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Stadium:
    """The complete in-memory stadium data model.

    Attributes:
        name: Common stadium name.
        fifa_name: Official FIFA tournament name.
        city: Host city name.
        capacity: Maximum seating capacity.
        zones: Dictionary mapping zone ID to Zone objects.
        adjacency: Adjacency list mapping zone ID to a list of Edges.
        facilities: List of all Facility objects.
        crowd_base: Dict mapping zone ID to static crowd string.
        crowd_sim: Dict of crowd simulation config parameters.
    """
    name: str
    fifa_name: str
    city: str
    capacity: int
    zones: dict[str, Zone]
    adjacency: dict[str, list[Edge]]
    facilities: list[Facility]
    crowd_base: dict[str, str]
    crowd_sim: dict[str, Any]

    def neighbors(self, zone_id: str) -> list[Edge]:
        """Return the outgoing edges from a zone.

        Args:
            zone_id: The ID of the origin zone.

        Returns:
            List of Edges. Returns empty list if zone not found.

        Raises:
            None

        Example:
            >>> edges = stadium.neighbors("gate_a")
        """
        return self.adjacency.get(zone_id, [])

    def facilities_of_types(self, types: set[str], *, accessible_only: bool) -> list[Facility]:
        """Return facilities matching the requested types.

        Args:
            types: Set of facility type strings to match.
            accessible_only: If True, exclude non-accessible facilities.

        Returns:
            List of matching Facility objects.

        Raises:
            None

        Example:
            >>> facs = stadium.facilities_of_types({"restroom"}, accessible_only=True)
        """
        return [
            f for f in self.facilities
            if f.type in types and (not accessible_only or f.accessible)
        ]

    def zone_name(self, zone_id: str, language: str) -> str:
        """Resolve the localized display name for a zone.

        Args:
            zone_id: The ID of the zone.
            language: ISO 639-1 language code.

        Returns:
            Localized name string, or the raw zone ID as fallback.

        Raises:
            None

        Example:
            >>> name = stadium.zone_name("gate_a", "en")
        """
        zone: Zone | None = self.zones.get(zone_id)
        if not zone:
            return zone_id
        return localized(zone.names, language) or zone_id

    def zone_type(self, zone_id: str) -> str:
        """Resolve the type category of a zone.

        Args:
            zone_id: The ID of the zone.

        Returns:
            Zone type string, or "unknown" if not found.

        Raises:
            None

        Example:
            >>> t = stadium.zone_type("gate_a")
        """
        zone: Zone | None = self.zones.get(zone_id)
        return zone.type if zone else "unknown"

    def base_crowd(self, zone_id: str) -> str:
        """Resolve the static base crowd level for a zone.

        Args:
            zone_id: The ID of the zone.

        Returns:
            Base crowd string ('low', 'medium', 'high'). Defaults to 'low'.

        Raises:
            None

        Example:
            >>> bc = stadium.base_crowd("gate_a")
        """
        return self.crowd_base.get(zone_id, "low")


def localized(dictionary: dict[str, str], language: str) -> str | None:
    """Extract the string for a given language code with English fallback.

    Args:
        dictionary: Mapping of language codes to localized strings.
        language: ISO 639-1 language code requested.

    Returns:
        The matching string, the English fallback, or None if neither exist.

    Raises:
        None

    Example:
        >>> localized({"en": "Hello", "es": "Hola"}, "es")
        'Hola'
    """
    if not dictionary:
        return None
    return dictionary.get(language, dictionary.get("en", next(iter(dictionary.values()), None)))


def _read_json(filename: str) -> dict[str, Any]:
    """Load a JSON fixture from the data directory.

    Args:
        filename: Name of the JSON file.

    Returns:
        The deserialized JSON dict.

    Raises:
        RuntimeError: If the fixture file cannot be read.

    Example:
        >>> data = _read_json("stadium.json")
        >>> "stadium" in data
        True
    """
    try:
        with (_DATA_DIR / filename).open(encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except Exception as e:
        raise RuntimeError(f"Failed to load {filename}: {e}") from e


def _parse_zones(raw: list[dict[str, Any]]) -> dict[str, Zone]:
    """Parse raw zone dicts into Zone dataclasses.

    Args:
        raw: List of dicts from JSON.

    Returns:
        Dict mapping zone ID to Zone instance.

    Raises:
        None

    Example:
        >>> zones = _parse_zones([{"id": "gate_a", "name": {"en": "Gate A"}, "type": "gate", "level": 0}])
        >>> zones["gate_a"].type
        'gate'
    """
    return {z["id"]: Zone(z["id"], z.get("name", {}), z["type"], z["level"]) for z in raw}


def _parse_edges(raw: list[dict[str, Any]]) -> dict[str, list[Edge]]:
    """Parse raw edge dicts into graph adjacency lists.

    Each edge in the JSON is treated as undirected: both (from→to) and
    (to→from) directions are added to the adjacency map so that Dijkstra
    can traverse the graph in either direction.

    Args:
        raw: List of dicts from JSON, each with keys ``from``, ``to``,
            ``distance``, ``means``, and optionally ``step_free``.

    Returns:
        Dict mapping origin zone ID to list of outgoing :class:`Edge` objects.

    Raises:
        None

    Example:
        >>> edges = _parse_edges([{"from": "gate_a", "to": "concourse_1",
        ...     "distance": 50, "means": "walk", "step_free": True}])
        >>> len(edges["gate_a"])
        1
    """
    graph: dict[str, list[Edge]] = {}
    for edge in raw:
        from_zone_id = edge["from"]
        to_zone_id = edge["to"]
        distance = edge["distance"]
        means = edge["means"]
        is_step_free = edge.get("step_free", True)
        graph.setdefault(from_zone_id, []).append(Edge(to_zone_id, distance, means, is_step_free))
        graph.setdefault(to_zone_id, []).append(Edge(from_zone_id, distance, means, is_step_free))
    return graph


def _parse_facilities(raw: list[dict[str, Any]]) -> list[Facility]:
    """Parse raw facility dicts into Facility dataclasses.

    Args:
        raw: List of dicts from JSON.

    Returns:
        List of Facility instances.

    Raises:
        None

    Example:
        >>> facs = _parse_facilities([{"id": "restroom_1", "name": {"en": "Restroom"},
        ...     "type": "restroom", "zone": "concourse_1", "accessible": True}])
        >>> facs[0].type
        'restroom'
    """
    return [
        Facility(f["id"], f.get("name", {}), f["type"], f["zone"], f["accessible"], f.get("landmark", {}))
        for f in raw
    ]


def _build_stadium() -> Stadium:
    """Assemble the Stadium singleton from the disk fixtures.

    Args:
        None

    Returns:
        The loaded Stadium instance.

    Raises:
        RuntimeError: If parsing fails.
    """
    s_data: dict[str, Any] = _read_json("stadium.json")
    f_data: dict[str, Any] = _read_json("facilities.json")
    c_data: dict[str, Any] = _read_json("crowd.json")

    return Stadium(
        name=s_data["stadium"]["name"],
        fifa_name=s_data["stadium"]["fifa_name"],
        city=s_data["stadium"]["city"],
        capacity=s_data["stadium"]["capacity"],
        zones=_parse_zones(s_data["zones"]),
        adjacency=_parse_edges(s_data["edges"]),
        facilities=_parse_facilities(f_data["facilities"]),
        crowd_base=c_data.get("base", {}),
        crowd_sim=c_data.get("simulation", {}),
    )


_STADIUM_CACHE: Stadium | None = None


def get_stadium() -> Stadium:
    """Return the application-wide cached Stadium singleton.

    Loads the fixture from disk on first call and returns the cached
    instance on all subsequent calls.

    Args:
        None

    Returns:
        The loaded Stadium singleton.

    Raises:
        RuntimeError: If the fixture file is missing or unparseable.

    Example:
        >>> s = get_stadium()
    """
    global _STADIUM_CACHE
    if _STADIUM_CACHE is None:
        _STADIUM_CACHE = _build_stadium()
        logger.info("Loaded stadium %s with %d zones", _STADIUM_CACHE.name, len(_STADIUM_CACHE.zones))
    return _STADIUM_CACHE
