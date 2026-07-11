"""
ArenaIQ — Dijkstra shortest-path routing over the stadium zone graph.

Implements the least-distance path search between any two zone nodes using
Dijkstra's algorithm with a min-heap priority queue. The graph is loaded
from :func:`~app.services.stadium_data.get_stadium` and is held in memory
for the process lifetime, making all path queries sub-millisecond.

Accessibility routing:
    When ``step_free_only=True``, edges whose ``step_free`` flag is
    ``False`` (i.e. stairs) are excluded from the traversal before the
    frontier is expanded. This guarantees that wheelchair and low-vision
    users receive routes that use only ramps and elevators.

Algorithm notes:
    The implementation uses ``heapq`` (a binary min-heap) for the priority
    queue. Stale entries (nodes re-inserted with a lower cost later) are
    skipped by comparing the popped cost against the best known cost.

Typical usage::

    from app.services.routing import find_path, path_distance
    from app.services.stadium_data import get_stadium

    stadium = get_stadium()
    path = find_path(stadium, "gate_a", "concourse_lower_sw")
    total_metres = path_distance(path) if path else None
"""

from __future__ import annotations

import heapq

from app.services.stadium_data import Edge, Stadium


def find_path(
    stadium: Stadium, start: str, goal: str, *, step_free_only: bool = False
) -> list[Edge] | None:
    """Find the shortest path between two zone nodes using Dijkstra's algorithm.

    Constructs a min-heap priority queue over (cumulative_distance, zone_id)
    pairs and expands the least-cost frontier node at each step. Stale queue
    entries are detected by comparing the popped cost to the best-known cost
    for that node and skipped if a shorter path has already been found.

    When ``step_free_only`` is ``True``, any edge whose ``step_free``
    attribute is ``False`` is filtered from the neighbor list before
    expansion, producing a route that uses only ramps and elevators.

    Args:
        stadium: The loaded :class:`~app.services.stadium_data.Stadium`
            containing the zone graph and adjacency list.
        start: Zone ID of the starting location.
        goal: Zone ID of the target destination.
        step_free_only: If ``True``, exclude stair edges to produce a
            wheelchair/visual-accessible route. Defaults to ``False``.

    Returns:
        An ordered list of :class:`~app.services.stadium_data.Edge` objects
        representing the shortest path from ``start`` to ``goal`` (inclusive).
        Returns an empty list when ``start == goal`` (already at destination).
        Returns ``None`` when no path exists under the given constraints.

    Raises:
        None: All error conditions are signalled via ``None`` return value
            rather than exceptions to simplify caller control flow.
    """
    if start == goal:
        # Already at the destination — zero-step route.
        return []
    if start not in stadium.zones or goal not in stadium.zones:
        # Unknown zone ID: no path possible.
        return None

    # Priority queue: (cumulative_distance, zone_id).
    # heapq is a min-heap, so the node with the lowest cost is always popped first.
    frontier: list[tuple[int, str]] = [(0, start)]
    best_cost: dict[str, int] = {start: 0}
    came_from: dict[str, tuple[str, Edge]] = {}

    while frontier:
        cost, node = heapq.heappop(frontier)

        if node == goal:
            # Reached the target — reconstruct the edge list from the predecessor map.
            return _reconstruct(came_from, goal)

        if cost > best_cost.get(node, int(1e9)):
            # Stale queue entry: a cheaper path to this node was already found.
            continue

        for edge in stadium.neighbors(node):
            if step_free_only and not edge.step_free:
                # Accessibility constraint: skip stair edges for step-free routing.
                continue
            new_cost = cost + edge.distance
            if new_cost < best_cost.get(edge.to, int(1e9)):
                # Found a shorter path to this neighbour — update and enqueue.
                best_cost[edge.to] = new_cost
                came_from[edge.to] = (node, edge)
                heapq.heappush(frontier, (new_cost, edge.to))

    # Exhausted the frontier without reaching the goal.
    return None


def _reconstruct(came_from: dict[str, tuple[str, Edge]], goal: str) -> list[Edge]:
    """Reconstruct the ordered edge list by walking the predecessor map backwards.

    Traces from ``goal`` back to the start node by following the
    ``came_from`` predecessor pointers, building the path in reverse, then
    reversing to produce the correct start-to-goal order.

    Args:
        came_from: Dict mapping each zone ID to the ``(predecessor_zone_id,
            edge)`` pair that led to it during Dijkstra traversal.
        goal: The zone ID of the destination reached by the search.

    Returns:
        An ordered list of :class:`~app.services.stadium_data.Edge` objects
        from the start zone to ``goal``, inclusive.
    """
    path: list[Edge] = []
    node = goal
    # Walk backwards through predecessors until we reach the start (no entry).
    while node in came_from:
        prev, edge = came_from[node]
        path.append(edge)
        node = prev
    # Reverse to produce start-to-goal ordering.
    path.reverse()
    return path


def path_distance(path: list[Edge]) -> int:
    """Compute the total walking distance of a route in metres.

    Sums the ``distance`` attribute of every edge in the path. Returns 0
    for an empty path (already at the destination).

    Args:
        path: Ordered list of :class:`~app.services.stadium_data.Edge`
            objects as returned by :func:`find_path`.

    Returns:
        Total distance in metres as a non-negative integer.
    """
    return sum(edge.distance for edge in path)
