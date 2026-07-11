"""Shortest-path routing over the stadium zone graph.

A tiny Dijkstra implementation finds the least-distance path between two zones.
When ``step_free_only`` is set (wheelchair / visual needs), edges that are not
step-free (e.g. stairs) are excluded, so accessible routes provably differ from
the default ones.
"""

from __future__ import annotations

import heapq

from app.services.stadium_data import Edge, Stadium


def find_path(
    stadium: Stadium, start: str, goal: str, *, step_free_only: bool = False
) -> list[Edge] | None:
    """Return the list of edges from ``start`` to ``goal``.

    Returns an empty list when ``start == goal``, and ``None`` when no route
    exists under the given constraints.
    """
    if start == goal:
        return []
    if start not in stadium.zones or goal not in stadium.zones:
        return None

    # Priority queue of (cumulative_distance, zone_id).
    frontier: list[tuple[int, str]] = [(0, start)]
    best_cost: dict[str, int] = {start: 0}
    came_from: dict[str, tuple[str, Edge]] = {}

    while frontier:
        cost, node = heapq.heappop(frontier)
        if node == goal:
            return _reconstruct(came_from, goal)
        if cost > best_cost.get(node, float("inf")):
            continue  # stale queue entry
        for edge in stadium.neighbors(node):
            if step_free_only and not edge.step_free:
                continue
            new_cost = cost + edge.distance
            if new_cost < best_cost.get(edge.to, float("inf")):
                best_cost[edge.to] = new_cost
                came_from[edge.to] = (node, edge)
                heapq.heappush(frontier, (new_cost, edge.to))

    return None


def _reconstruct(came_from: dict[str, tuple[str, Edge]], goal: str) -> list[Edge]:
    """Walk the predecessor map back to the start and return edges in order."""
    path: list[Edge] = []
    node = goal
    while node in came_from:
        prev, edge = came_from[node]
        path.append(edge)
        node = prev
    path.reverse()
    return path


def path_distance(path: list[Edge]) -> int:
    """Total distance of a path (0 for an empty path)."""
    return sum(edge.distance for edge in path)
