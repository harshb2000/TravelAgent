from collections import deque

from models.knowledge_state import (
    KnowledgeState,
    RouteKey,
    RouteKnowledge,
    DateRange,
    TravelOption,
    UserContext,
)
from specialists.transportation import TransportationSpecialist
from tools.base import BaseTool


# ---------------------------------------------------------------------------
# BFS helpers
# ---------------------------------------------------------------------------

def _build_route_graph(
    routes: dict[RouteKey, RouteKnowledge],
    date_range: DateRange,
) -> dict[str, set[str]]:
    """
    Build a traversal graph from stored routes for the given date range.
    Non-flight routes (stored under DateRange('any')) are reversible — a stored
    A→B ground edge also implies B→A can be traversed without being stored separately.
    """
    any_date_range = DateRange("any")
    graph: dict[str, set[str]] = {}
    for route_key, route_knowledge in routes.items():
        relevant = [
            o for dr, opts in route_knowledge.options.items()
            if dr in (date_range, any_date_range) for o in opts
        ]
        has_flight = any("flight" in o.mode for o in relevant)
        has_ground = any("flight" not in o.mode for o in relevant)
        if has_flight or has_ground:
            graph.setdefault(route_key.origin, set()).add(route_key.destination)
        if has_ground:
            graph.setdefault(route_key.destination, set()).add(route_key.origin)
    return graph


def _reverse_graph(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    """Return the transpose of a directed graph."""
    result: dict[str, set[str]] = {}
    for node, neighbors in graph.items():
        for neighbor in neighbors:
            result.setdefault(neighbor, set()).add(node)
    return result


def bfs_find_path(
    origin: str,
    destination: str,
    date_range: DateRange,
    routes: dict[RouteKey, RouteKnowledge],
) -> list[str] | None:
    """Return the node sequence forming a path from origin to destination, or None if unreachable."""
    if origin == destination:
        return [origin]

    graph = _build_route_graph(routes, date_range)
    parent: dict[str, str | None] = {origin: None}
    queue: deque[str] = deque([origin])
    while queue:
        current = queue.popleft()
        for neighbor in graph.get(current, set()):
            if neighbor == destination:
                path = [destination, current]
                node = current
                while parent[node] is not None:
                    node = parent[node]  # type: ignore[assignment]
                    path.append(node)
                return list(reversed(path))
            if neighbor not in parent:
                parent[neighbor] = current
                queue.append(neighbor)
    return None


_EXISTING_EDGES_LIMIT = 10


def bfs_distances(start: str, graph: dict[str, set[str]]) -> dict[str, int]:
    distances: dict[str, int] = {start: 0}
    queue: deque[str] = deque([start])
    while queue:
        current = queue.popleft()
        for neighbor in graph.get(current, set()):
            if neighbor not in distances:
                distances[neighbor] = distances[current] + 1
                queue.append(neighbor)
    return distances


def _select_relevant_route_keys(
    origin: str,
    destination: str,
    date_range: DateRange,
    knowledge: KnowledgeState,
    limit: int = _EXISTING_EDGES_LIMIT,
) -> list[RouteKey]:
    """
    Return route keys reachable from origin (forward) or that can reach destination (backward),
    ordered by distance from either endpoint, with a preference for novel nodes when trimming.
    """
    any_date_range = DateRange("any")
    forward_graph = _build_route_graph(knowledge.routes, date_range)
    backward_graph = _reverse_graph(forward_graph)

    forward_dist = bfs_distances(origin, forward_graph)
    backward_dist = bfs_distances(destination, backward_graph)

    candidates: list[tuple[float, RouteKey]] = []
    for route_key, route_knowledge in knowledge.routes.items():
        if not any(dr in (date_range, any_date_range) and opts for dr, opts in route_knowledge.options.items()):
            continue
        in_forward = route_key.origin in forward_dist
        in_backward = route_key.destination in backward_dist
        if not in_forward and not in_backward:
            continue
        distance = min(
            forward_dist.get(route_key.origin, float("inf")),
            backward_dist.get(route_key.destination, float("inf")),
        )
        candidates.append((distance, route_key))

    candidates.sort(key=lambda pair: pair[0])

    selected: dict[RouteKey, None] = {}  # insertion-ordered set: O(1) lookup, preserves priority order
    covered_nodes: set[str] = set()
    i = 0
    while i < len(candidates) and len(selected) < limit:
        current_distance = candidates[i][0]
        j = i
        while j < len(candidates) and candidates[j][0] == current_distance:
            j += 1
        group = [route_key for _, route_key in candidates[i:j]]

        remaining = limit - len(selected)
        # Prefer edges that introduce at least one node not yet covered
        ordered = (
            group if len(group) <= remaining
            else [rk for rk in group if rk.origin not in covered_nodes or rk.destination not in covered_nodes]
                 + [rk for rk in group if rk.origin in covered_nodes and rk.destination in covered_nodes]
        )
        for route_key in ordered:
            if len(selected) >= limit:
                break
            # Skip ground-only routes whose reverse is already selected — they're redundant
            # because the specialist is told ground options are reversible.
            rk_knowledge = knowledge.routes[route_key]
            relevant = [o for dr, opts in rk_knowledge.options.items() if dr in (date_range, any_date_range) for o in opts]
            has_flight = any("flight" in o.mode for o in relevant)
            if not has_flight and RouteKey(route_key.destination, route_key.origin) in selected:
                continue
            selected[route_key] = None
            covered_nodes.update((route_key.origin, route_key.destination))
        i = j

    return list(selected)


def _existing_edges_summary(
    route_key: RouteKey,
    date_range: DateRange,
    knowledge: KnowledgeState,
) -> str | None:
    """Build a ranked summary of partial edges relevant to this route for the specialist."""
    any_date_range = DateRange("any")
    selected_keys = _select_relevant_route_keys(
        route_key.origin, route_key.destination, date_range, knowledge
    )
    lines: list[str] = []
    for selected_route_key in selected_keys:
        route_knowledge = knowledge.routes[selected_route_key]
        for stored_date_range, options in route_knowledge.options.items():
            if stored_date_range in (date_range, any_date_range) and options:
                option_summary = ", ".join(
                    f"{option.mode} ${option.cost_usd:.0f}" if option.cost_usd is not None else option.mode
                    for option in options[:2]
                )
                date_label = "any date" if stored_date_range.label == "any" else stored_date_range.label
                lines.append(
                    f"  {selected_route_key.origin} to {selected_route_key.destination}"
                    f" ({date_label}): {option_summary}"
                )
    return "\n".join(lines) if lines else None


# ---------------------------------------------------------------------------
# Route summary
# ---------------------------------------------------------------------------

def _flight_option_summary(option: TravelOption, label: str) -> str:
    trip_type = "return" if "return" in option.mode else "one-way"
    operator = f" · {option.operator}" if option.operator else ""
    stops = option.flight.stops if option.flight else "?"
    duration = f" · {option.duration_min // 60}h{option.duration_min % 60:02d}m" if option.duration_min else ""
    return f"{label}: ${option.cost_usd:.0f} {trip_type}{operator} · {stops} stop(s){duration}"


def _ground_option_summary(option: TravelOption, label: str) -> str:
    duration = f" · {option.duration_min}min" if option.duration_min else ""
    return f"{label}: {option.mode} ${option.cost_usd:.0f}{duration}"


def _leg_summary_lines(
    leg_origin: str,
    leg_destination: str,
    date_range: DateRange,
    route_knowledge: RouteKnowledge,
) -> list[str]:
    """Return indented summary lines for a single leg, applying cheapest/fastest per mode group."""
    any_date_range = DateRange("any")
    all_options: list[TravelOption] = []
    for stored_date_range, options in route_knowledge.options.items():
        if stored_date_range in (date_range, any_date_range):
            all_options.extend(options)

    flight_options = [o for o in all_options if "flight" in o.mode]
    ground_options = [o for o in all_options if "flight" not in o.mode]

    lines: list[str] = [f"  {leg_origin} to {leg_destination}:"]

    if flight_options:
        flight_by_mode: dict[str, list[TravelOption]] = {}
        for o in flight_options:
            flight_by_mode.setdefault(o.mode, []).append(o)
        for mode, mode_options in flight_by_mode.items():
            mode_label = "return" if "return" in mode else "one-way"
            cheapest = min(mode_options, key=lambda o: o.cost_usd or float("inf"))
            fastest = min(mode_options, key=lambda o: o.duration_min or float("inf"))
            fewest_stops = min(mode_options, key=lambda o: (o.flight.stops if o.flight else float("inf")))
            lines.append(_flight_option_summary(cheapest, f"    cheapest {mode_label}"))
            if fastest is not cheapest:
                lines.append(_flight_option_summary(fastest, f"    fastest {mode_label}"))
            if fewest_stops is not cheapest and fewest_stops is not fastest:
                lines.append(_flight_option_summary(fewest_stops, f"    fewest stops {mode_label}"))
    elif ground_options:
        cheapest = min(ground_options, key=lambda o: o.cost_usd or float("inf"))
        fastest = min(ground_options, key=lambda o: o.duration_min or float("inf"))
        lines.append(_ground_option_summary(cheapest, "    cheapest"))
        if fastest is not cheapest:
            lines.append(_ground_option_summary(fastest, "    fastest"))

    return lines


def _build_route_summary(
    route_key: RouteKey,
    date_range: DateRange,
    knowledge: KnowledgeState,
    is_new: bool,
    is_round_trip: bool = False,
) -> str:
    """
    Summarise all edges that lie on any path from origin to destination.
    An edge qualifies when its origin is forward-reachable from the journey origin
    AND its destination is backward-reachable from the journey destination (intersection).
    Edges are grouped by their forward distance so parallel options at the same hop level
    appear together.
    """
    tag = "[new]" if is_new else "[cached]"

    forward_graph = _build_route_graph(knowledge.routes, date_range)
    backward_graph = _reverse_graph(forward_graph)

    forward_dist = bfs_distances(route_key.origin, forward_graph)
    backward_dist = bfs_distances(route_key.destination, backward_graph)

    any_date_range = DateRange("any")
    edges_by_level: dict[int, list[RouteKey]] = {}
    return_flight_keys: list[RouteKey] = []
    for stored_key, stored_knowledge in knowledge.routes.items():
        options_for_range = [
            o for dr, opts in stored_knowledge.options.items()
            if dr in (date_range, any_date_range) for o in opts
        ]
        if not options_for_range:
            continue
        # Edges whose options are exclusively return flights belong in the return section,
        # not the outbound path, so we collect them separately.
        if all(o.mode == "flight/return" for o in options_for_range):
            if is_round_trip:
                return_flight_keys.append(stored_key)
            continue
        if stored_key.origin not in forward_dist or stored_key.destination not in backward_dist:
            continue
        level = forward_dist[stored_key.origin]
        edges_by_level.setdefault(level, []).append(stored_key)

    assert edges_by_level, "_build_route_summary called but no edges on path — caller must verify path exists first"

    lines = [f"{route_key.origin} to {route_key.destination} ({date_range.label})  {tag}"]
    for level in sorted(edges_by_level):
        for leg_key in edges_by_level[level]:
            lines.extend(_leg_summary_lines(leg_key.origin, leg_key.destination, date_range, knowledge.routes[leg_key]))

    if return_flight_keys:
        lines.append("Return flight:")
        for return_key in return_flight_keys:
            lines.extend(_leg_summary_lines(return_key.origin, return_key.destination, date_range, knowledge.routes[return_key]))

    return "\n".join(lines)


def _routes_resolved(
    origin: str,
    destination: str,
    date_range: DateRange,
    knowledge: KnowledgeState,
    is_round_trip: bool,
) -> bool:
    """Return True when all required paths exist in the knowledge state."""
    forward = bfs_find_path(origin, destination, date_range, knowledge.routes)
    if forward is None:
        return False
    if not is_round_trip:
        return True
    return bfs_find_path(destination, origin, date_range, knowledge.routes) is not None


# ---------------------------------------------------------------------------
# Wrapper tool
# ---------------------------------------------------------------------------

class TransportationWrapperTool(BaseTool):
    name = "transportation"
    description = (
        "Find flight and ground transfer options for a single city-to-city route. "
        "The specialist resolves IATA codes, searches flights, and finds transfers "
        "to compose a complete path."
    )
    parameters = {
        "type": "object",
        "properties": {
            "origin": {
                "type": "string",
                "description": "City-level — a specific routeable city, not a region or country.",
            },
            "destination": {
                "type": "string",
                "description": "City-level — a specific routeable city, not a region or country.",
            },
            "date_range": {
                "type": "string",
                "description": (
                    "Departure date or date range string, e.g. '2026-07-13' or 'July 2026'. "
                    "Omit for date-invariant ground-only routes."
                ),
            },
            "trip_type": {
                "type": "string",
                "enum": ["one_way", "round_trip"],
                "description": (
                    "'round_trip' only when this specific origin→destination leg has a return "
                    "flight back to the same origin as part of the trip (e.g. a simple A→B→A "
                    "holiday). Use 'one_way' for every leg of a multi-city itinerary and for "
                    "any one-directional journey. Defaults to 'one_way'."
                ),
            },
        },
        "required": ["origin", "destination"],
    }

    def __init__(
        self,
        specialist: TransportationSpecialist,
        knowledge: KnowledgeState,
        user_context: UserContext,
    ):
        self._specialist = specialist
        self._knowledge = knowledge
        self._user_context = user_context

    def execute(self, **kwargs) -> dict:
        origin: str = kwargs["origin"]
        destination: str = kwargs["destination"]
        user_context: str = self._user_context.context
        date_range = DateRange.from_string(kwargs.get("date_range", "any"))
        trip_type: str = kwargs.get("trip_type", "one_way")
        route_key = RouteKey(origin, destination)
        knowledge = self._knowledge
        is_round_trip = trip_type == "round_trip"

        if _routes_resolved(origin, destination, date_range, knowledge, is_round_trip):
            return {"status": "ok", "summary": _build_route_summary(route_key, date_range, knowledge, is_new=False, is_round_trip=is_round_trip), "from_cache": True}

        any_date_range = DateRange("any")
        success = False

        for _ in range(2):  # initial run + one retry if path still incomplete
            existing_edges = _existing_edges_summary(route_key, date_range, knowledge)

            try:
                options = self._specialist.run(
                    routes=[(route_key, date_range)],
                    user_context=user_context,
                    existing_edges=existing_edges,
                    max_iterations=3,
                    trip_type=trip_type,
                )
            except Exception as e:
                return {"status": "error", "summary": f"TransportationSpecialist failed: {e}"}

            # Flight options belong to this route's DateRange; ground options are date-invariant.
            options_by_key: dict[tuple[str, str, DateRange], list[TravelOption]] = {}
            for option in options:
                option_date_range = date_range if "flight" in option.mode else any_date_range
                options_by_key.setdefault((option.origin, option.destination, option_date_range), []).append(option)

            for (leg_origin, leg_destination, leg_date_range), grouped_options in options_by_key.items():
                knowledge.update_route(leg_origin, leg_destination, leg_date_range, grouped_options)

            if _routes_resolved(origin, destination, date_range, knowledge, is_round_trip):
                success = True
                break

        if not success:
            result: dict = {
                "status": "failed",
                "summary": f"Could not find a complete path from {origin} to {destination} after 2 attempts.",
            }
            partial = _existing_edges_summary(route_key, date_range, knowledge)
            if partial:
                result["partial_summary"] = partial
            return result

        return {"status": "ok", "summary": _build_route_summary(route_key, date_range, knowledge, is_new=True, is_round_trip=is_round_trip)}
