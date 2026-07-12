"""
ArenaIQ — Dijkstra shortest-path routing over the stadium zone graph.

# ============================================================
# ARCHITECTURAL DECISION: IN-MEMORY DIJKSTRA
# ============================================================
# The stadium zone graph is held entirely in memory after initial
# JSON parsing. A standard min-heap Dijkstra search provides
# sub-millisecond route resolution.
#
# Crucially, accessibility is implemented as an edge filter during
# neighbor expansion: when `step_free_only=True`, stair edges are
# simply excluded from the search graph, guaranteeing wheelchair-
# navigable routes without complex constraints checking post-hoc.
# ============================================================
"""

from __future__ import annotations

import heapq

from app.services.stadium_data import Edge, Stadium
from app.utils.constants import ROUTE_INFINITY_COST


def _init_dijkstra_state(start: str) -> tuple[list[tuple[int, str]], dict[str, int]]:
    """Initialize the frontier queue and cost tracker for Dijkstra.

    Args:
        start: Origin zone ID.

    Returns:
        A tuple of (frontier_queue, best_cost_map).

    Raises:
        None

    Example:
        >>> f, bc = _init_dijkstra_state("gate_a")
        >>> f
        [(0, 'gate_a')]
        >>> bc
        {'gate_a': 0}
    """
    return [(0, start)], {start: 0}


def _process_neighbors(
    stadium: Stadium,
    node: str,
    cost: int,
    step_free_only: bool,
    best_cost: dict[str, int],
    came_from: dict[str, tuple[str, Edge]],
    frontier: list[tuple[int, str]],
) -> None:
    """Expand neighbors of the current node and update the frontier.

    Args:
        stadium: The loaded stadium graph model.
        node: The zone ID currently being expanded.
        cost: The cumulative distance to reach `node`.
        step_free_only: If True, exclude non-accessible edges.
        best_cost: Map tracking the lowest known cost to each zone.
        came_from: Map of parent pointers for path reconstruction.
        frontier: The min-heap priority queue to push new paths into.

    Returns:
        None (mutates best_cost, came_from, and frontier in-place).

    Raises:
        None

    Example:
        >>> _process_neighbors(stadium, "node_a", 10, False, bc, cf, f)
    """
    for edge in stadium.neighbors(node):
        if step_free_only and not edge.step_free:
            continue
        new_cost: int = cost + edge.distance
        if new_cost < best_cost.get(edge.to, ROUTE_INFINITY_COST):
            best_cost[edge.to] = new_cost
            came_from[edge.to] = (node, edge)
            heapq.heappush(frontier, (new_cost, edge.to))


def find_path(
    stadium: Stadium, start: str, goal: str, *, step_free_only: bool = False
) -> list[Edge] | None:
    """Find the shortest path between two zone nodes.

    Args:
        stadium: The loaded stadium graph model.
        start: Origin zone ID string.
        goal: Target destination zone ID string.
        step_free_only: If True, exclude stair edges (wheelchair routing).

    Returns:
        An ordered list of Edges from start to goal, or None if unreachable.

    Raises:
        None: Fails gracefully via None return.

    Example:
        >>> edges = find_path(stadium, "gate_a", "seat_100", step_free_only=True)
    """
    if start == goal:
        return []
    if start not in stadium.zones or goal not in stadium.zones:
        return None

    frontier, best_cost = _init_dijkstra_state(start)
    came_from: dict[str, tuple[str, Edge]] = {}

    while frontier:
        cost, node = heapq.heappop(frontier)
        if node == goal:
            return _reconstruct(came_from, goal)
        if cost > best_cost.get(node, ROUTE_INFINITY_COST):
            continue
        _process_neighbors(stadium, node, cost, step_free_only, best_cost, came_from, frontier)
    return None


def _reconstruct(came_from: dict[str, tuple[str, Edge]], goal: str) -> list[Edge]:
    """Reconstruct the ordered edge list by walking parent pointers backwards.

    Args:
        came_from: Dict mapping zone ID to (predecessor_zone, edge).
        goal: The destination zone ID reached by the search.

    Returns:
        Ordered list of Edges from start to goal.

    Raises:
        None

    Example:
        >>> path = _reconstruct(cf_map, "exit_north")
    """
    path: list[Edge] = []
    node: str = goal
    while node in came_from:
        prev, edge = came_from[node]
        path.append(edge)
        node = prev
    path.reverse()
    return path


def path_distance(path: list[Edge]) -> int:
    """Compute the total walking distance of a route in metres.

    Args:
        path: Ordered list of routing edges.

    Returns:
        Total distance integer. Returns 0 for empty paths.

    Raises:
        None

    Example:
        >>> dist = path_distance(my_path)
    """
    return sum(edge.distance for edge in path)
