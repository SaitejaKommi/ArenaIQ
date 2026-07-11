"""
ArenaIQ — Stadium JSON fixture loading and in-memory graph model.

The three JSON fixtures (``stadium.json``, ``facilities.json``,
``crowd.json``) are read **once** at first access and cached for the entire
process lifetime using :func:`functools.lru_cache`. This ensures that
pathfinding and facility lookups during peak crowd periods carry no I/O
overhead after the initial load.

Graph model:
    Stadium zones are nodes and the edges between them form an undirected,
    weighted graph. Each edge is stored in both directions in the adjacency
    list so that Dijkstra traversal can proceed in either direction without
    special-casing. Edge weights are walking distances in metres.

Localization:
    Zone names, facility names, and landmark descriptions are stored as
    ``I18n`` dicts (``{"en": ..., "es": ..., "fr": ...}``) within the
    fixture JSON. The :func:`localized` helper resolves them to a single
    string for the requested language, falling back to English then any
    available language.

Typical usage::

    from app.services.stadium_data import get_stadium, localized

    stadium = get_stadium()                         # cached singleton
    name = stadium.zone_name("gate_a", "es")        # "Puerta A (suroeste)"
    crowd = stadium.base_crowd("concourse_lower_sw") # "medium"
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"

#: Localized text type: a mapping of ISO 639-1 language code → translated string.
I18n = dict[str, str]

_DEFAULT_LANG: str = "en"


def localized(mapping: I18n | None, language: str) -> str | None:
    """Resolve a localized string with English and any-language fallbacks.

    Looks up ``language`` in ``mapping``. If absent, tries the English key
    (``"en"``). If that is also absent, returns the first available value.
    Returns ``None`` only when ``mapping`` is ``None`` or empty.

    Args:
        mapping: A dict mapping language codes to translated strings, or
            ``None`` if no localization data is available for this field.
        language: The desired ISO 639-1 language code (e.g. ``"en"``).

    Returns:
        The best available localized string, or ``None`` if ``mapping``
        is falsy (``None`` or empty dict).
    """
    if not mapping:
        return None
    return mapping.get(language) or mapping.get(_DEFAULT_LANG) or next(iter(mapping.values()))


@dataclass
class Zone:
    """A navigable location node in the stadium zone graph.

    Zones are connected by :class:`Edge` objects to form the pathfinding
    graph. Zone names are stored as localized ``I18n`` mappings so the UI
    can display them in the fan's preferred language.

    Attributes:
        id: Unique zone identifier (e.g. ``"gate_a"``, ``"concourse_lower_sw"``).
        names: Localized display names mapping language code → name string.
        type: Zone category (``"gate"``, ``"concourse"``, or ``"seating"``).
        level: Physical level descriptor (e.g. ``"ground"``, ``"lower"``,
            ``"upper"``).
    """

    id: str
    names: I18n
    type: str
    level: str


@dataclass(frozen=True)
class Edge:
    """A directed connection from one zone to another in the stadium graph.

    Edges are stored in both directions in the adjacency list, so the graph
    is effectively undirected. The ``frozen=True`` dataclass is hashable and
    immutable, making it safe to use as a dict key in the Dijkstra frontier.

    Attributes:
        to: Zone ID of the destination node.
        means: Travel means (``"walk"``, ``"ramp"``, ``"elevator"``,
            ``"stairs"``).
        step_free: ``True`` if this edge does not require climbing steps —
            used to filter accessible-only routes for wheelchair/visual users.
        distance: Approximate walking distance in metres for this edge.
    """

    to: str
    means: str
    step_free: bool
    distance: int


@dataclass
class Facility:
    """A named point of interest located within a stadium zone.

    Facilities are the destinations that fans navigate to (restrooms, gates,
    first-aid posts, concessions, etc.). Both ``names`` and ``landmarks``
    are localized to support multilingual route instructions.

    Attributes:
        id: Unique facility identifier (e.g. ``"restroom_lower_se"``).
        names: Localized display names mapping language code → name string.
        type: Facility category (e.g. ``"restroom"``, ``"gate"``,
            ``"first_aid"``).
        zone: ID of the zone where this facility is located.
        accessible: ``True`` if the facility is wheelchair-accessible.
        landmarks: Optional localized landmark descriptions used in
            screen-reader-optimized route instructions.
    """

    id: str
    names: I18n
    type: str
    zone: str
    accessible: bool
    landmarks: I18n | None = None


@dataclass
class Stadium:
    """In-memory model of the stadium: zones, adjacency graph, facilities, and crowd data.

    Constructed once from the three JSON fixtures and cached for the process
    lifetime. Exposes a small, well-typed API over the raw data so callers
    never need to parse JSON dictionaries directly.

    Attributes:
        name: Official stadium name (e.g. ``"MetLife Stadium"``).
        fifa_name: FIFA tournament name for the venue.
        city: City and state/country string.
        capacity: Seating capacity as an integer.
        zones: Dict mapping zone ID → :class:`Zone` for O(1) zone lookup.
        adjacency: Dict mapping zone ID → list of outgoing :class:`Edge`
            objects forming the pathfinding graph.
        facilities: List of all :class:`Facility` objects in the stadium.
        crowd_base: Dict mapping zone ID → base crowd level string.
        crowd_sim: Crowd simulation parameters loaded from ``crowd.json``.
    """

    name: str
    fifa_name: str
    city: str
    capacity: int
    zones: dict[str, Zone]
    adjacency: dict[str, list[Edge]]
    facilities: list[Facility]
    crowd_base: dict[str, str]
    crowd_sim: dict[str, Any] = field(default_factory=dict)

    def zone_ids(self) -> frozenset[str]:
        """Return the frozenset of all valid zone IDs.

        Used by the Pydantic validator in :class:`~app.models.schemas.UserContext`
        to reject requests with unknown ``current_location`` values.

        Returns:
            A frozenset of zone ID strings loaded from the fixture.
        """
        return frozenset(self.zones)

    def zone_name(self, zone_id: str, language: str = _DEFAULT_LANG) -> str:
        """Return the localized display name for a zone.

        Falls back to the zone ID string itself if the zone is unknown or
        has no localized name for the requested language.

        Args:
            zone_id: The zone identifier to look up.
            language: ISO 639-1 language code for the desired translation.
                Defaults to ``"en"``.

        Returns:
            Localized zone name string, or the raw ``zone_id`` as a fallback.
        """
        zone = self.zones.get(zone_id)
        return (localized(zone.names, language) or zone_id) if zone else zone_id

    def zone_type(self, zone_id: str) -> str:
        """Return the type string for a zone (e.g. ``"gate"``, ``"concourse"``).

        Used by the crowd simulation module to determine whether surge
        rules apply to a given zone.

        Args:
            zone_id: The zone identifier to look up.

        Returns:
            The zone type string, or an empty string if the zone is unknown.
        """
        zone = self.zones.get(zone_id)
        return zone.type if zone else ""

    def neighbors(self, zone_id: str) -> list[Edge]:
        """Return the list of outgoing edges from a zone node.

        Used by the Dijkstra routing algorithm to enumerate reachable
        neighbors during graph traversal.

        Args:
            zone_id: The zone identifier whose neighbors are requested.

        Returns:
            List of :class:`Edge` objects originating from ``zone_id``.
            Returns an empty list for unknown zone IDs.
        """
        return self.adjacency.get(zone_id, [])

    def facilities_of_types(
        self, types: set[str], *, accessible_only: bool = False
    ) -> list[Facility]:
        """Return facilities whose type is in ``types``, optionally filtering by accessibility.

        Args:
            types: Set of facility type strings to include in the results
                (e.g. ``{"restroom", "accessible_restroom"}``).
            accessible_only: If ``True``, only facilities with
                ``accessible=True`` are returned. Defaults to ``False``.

        Returns:
            A list of matching :class:`Facility` objects in fixture order.
        """
        return [
            f
            for f in self.facilities
            if f.type in types and (f.accessible or not accessible_only)
        ]

    def base_crowd(self, zone_id: str) -> str:
        """Return the static base crowd level for a zone from the fixture.

        The base level is the crowd density before any time-based simulation
        is applied. Unknown zones default to ``"low"``.

        Args:
            zone_id: The zone identifier to query.

        Returns:
            One of ``"low"``, ``"medium"``, or ``"high"``.
        """
        return self.crowd_base.get(zone_id, "low")


def _read_json(filename: str) -> dict[str, Any]:
    """Load and parse a JSON fixture file from the data directory.

    Args:
        filename: The base filename (e.g. ``"stadium.json"``) relative to
            the ``data/`` directory next to the ``app/`` package.

    Returns:
        The parsed JSON content as a Python dict.

    Raises:
        FileNotFoundError: If the fixture file does not exist at the
            expected path under ``_DATA_DIR``.
        json.JSONDecodeError: If the file content is not valid JSON.
    """
    with (_DATA_DIR / filename).open(encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[no-any-return]


def _build_stadium() -> Stadium:
    """Parse the three JSON fixtures and assemble an in-memory :class:`Stadium`.

    Reads ``stadium.json`` (zones and edges), ``facilities.json`` (points of
    interest), and ``crowd.json`` (base levels and simulation config).
    Builds a bidirectional adjacency list so that the Dijkstra implementation
    in :mod:`app.services.routing` can traverse the graph in either direction.

    Returns:
        A fully populated :class:`Stadium` instance ready for pathfinding
        and crowd simulation queries.

    Raises:
        FileNotFoundError: If any of the three fixture files is missing.
        KeyError: If a required field is absent from a fixture JSON object.
    """
    stadium_raw = _read_json("stadium.json")
    facilities_raw = _read_json("facilities.json")
    crowd_raw = _read_json("crowd.json")

    # Build zone lookup dict: zone_id → Zone dataclass.
    zones: dict[str, Zone] = {
        z["id"]: Zone(id=z["id"], names=z["name"], type=z["type"], level=z["level"])
        for z in stadium_raw["zones"]
    }

    # Build an undirected adjacency list from the directed edge list.
    # Each edge is stored in both directions to allow bidirectional traversal.
    adjacency: dict[str, list[Edge]] = {zid: [] for zid in zones}
    for e in stadium_raw["edges"]:
        src, dst = e["from"], e["to"]
        adjacency[src].append(
            Edge(to=dst, means=e["means"], step_free=e["step_free"], distance=e["distance"])
        )
        adjacency[dst].append(
            Edge(to=src, means=e["means"], step_free=e["step_free"], distance=e["distance"])
        )

    facilities: list[Facility] = [
        Facility(
            id=f["id"],
            names=f["name"],
            type=f["type"],
            zone=f["zone"],
            accessible=f["accessible"],
            landmarks=f.get("landmark"),
        )
        for f in facilities_raw["facilities"]
    ]

    meta = stadium_raw["stadium"]
    return Stadium(
        name=meta["name"],
        fifa_name=meta["fifa_name"],
        city=meta["city"],
        capacity=meta["capacity"],
        zones=zones,
        adjacency=adjacency,
        facilities=facilities,
        crowd_base=dict(crowd_raw["base"]),
        crowd_sim=dict(crowd_raw.get("simulation", {})),
    )


@lru_cache(maxsize=1)
def get_stadium() -> Stadium:
    """Return the process-wide cached :class:`Stadium` singleton.

    Loads and parses the JSON fixtures on first call via :func:`_build_stadium`,
    then caches the result for all subsequent calls using ``lru_cache``.
    This guarantees that fixture I/O and graph construction happen at most
    once per process lifetime, even under concurrent request load.

    Returns:
        The singleton :class:`Stadium` instance populated from the JSON fixtures.

    Raises:
        FileNotFoundError: If any fixture file is missing (propagated from
            :func:`_build_stadium` on first call only).
    """
    return _build_stadium()
