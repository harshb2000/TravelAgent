import json
from unittest.mock import MagicMock

import pytest

from tests.helpers import make_llm, stop_msg, tool_call_msg
from models.knowledge_state import (
    KnowledgeState,
    TravelOption,
    RouteKey,
    DateRange,
    UserContext,
)
from models.flights import FlightOption
from specialists.transportation import TransportationSpecialist
from tools.base import BaseTool
from tools.transportation_wrapper import (
    bfs_find_path as _bfs_find_path,
    _select_relevant_route_keys,
    _build_route_summary,
    TransportationWrapperTool,
)


# ---------------------------------------------------------------------------
# Shared fixtures / builders
# ---------------------------------------------------------------------------

DR = DateRange.from_string("2026-07-13")
ANY = DateRange("any")


def _flight_option(**kwargs) -> FlightOption:
    defaults = dict(
        airline="Air India", flight_number="AI 307",
        price_usd=450.0, stops=1, duration_min=660,
        departure="2026-07-13 01:30", arrival="2026-07-13 13:30",
        origin_iata="BOM", destination_iata="NRT",
    )
    return FlightOption(**{**defaults, **kwargs})


def _opt(mode, origin, dest, cost=None, duration=None, stops=None, fl=None):
    return TravelOption(
        mode=mode, origin=origin, destination=dest,
        cost_usd=cost, duration_min=duration, flight=fl,
    )


def _options_json(options: list[TravelOption]) -> str:
    return json.dumps([o.model_dump() for o in options])


def _make_specialist(chat_returns):
    llm = make_llm()
    llm.chat.side_effect = chat_returns if isinstance(chat_returns, list) else [chat_returns]
    return TransportationSpecialist(llm, []), llm


def _make_wrapper(ks: KnowledgeState | None = None):
    ks = ks or KnowledgeState()
    llm = make_llm()
    llm.chat.return_value = stop_msg(_options_json([]))
    specialist = TransportationSpecialist(llm, [])
    return TransportationWrapperTool(specialist, ks, UserContext()), specialist, ks, llm


def _populate_complete_path(ks: KnowledgeState, dr: DateRange) -> None:
    """Seed KnowledgeState with a complete Mumbai → Tokyo path."""
    ks.update_route("Mumbai", "BOM Airport", ANY, [
        _opt("taxi", "Mumbai", "BOM Airport", cost=30),
    ])
    ks.update_route("BOM Airport", "NRT Airport", dr, [
        _opt("flight/one-way", "BOM Airport", "NRT Airport", cost=450, fl=_flight_option()),
    ])
    ks.update_route("NRT Airport", "Tokyo", ANY, [
        _opt("metro", "NRT Airport", "Tokyo", cost=15),
    ])


def _populate_multi_path_ks() -> KnowledgeState:
    """
    Two departure airports (BOM, NMI) and two arrival airports (NRT, HND),
    plus both one-way and return flights on the BOM→NRT leg.
    Delhi edge is unrelated and should never appear.
    """
    ks = KnowledgeState()
    ks.update_route("Mumbai", "BOM Airport", ANY, [
        _opt("taxi",  "Mumbai", "BOM Airport", cost=30, duration=55),
        _opt("uber",  "Mumbai", "BOM Airport", cost=45, duration=38),
    ])
    ks.update_route("Mumbai", "NMI Airport", ANY, [
        _opt("train", "Mumbai", "NMI Airport", cost=12, duration=70),
    ])
    ks.update_route("BOM Airport", "NRT Airport", DR, [
        _opt("flight/one-way", "BOM Airport", "NRT Airport", cost=450, duration=660,
             fl=_flight_option(price_usd=450, duration_min=660, stops=1)),
        _opt("flight/one-way", "BOM Airport", "NRT Airport", cost=520, duration=540,
             fl=_flight_option(price_usd=520, duration_min=540, stops=0)),
        _opt("flight/return",  "BOM Airport", "NRT Airport", cost=820, duration=660,
             fl=_flight_option(price_usd=820, duration_min=660, stops=1)),
        _opt("flight/return",  "BOM Airport", "NRT Airport", cost=900, duration=540,
             fl=_flight_option(price_usd=900, duration_min=540, stops=0)),
    ])
    ks.update_route("NMI Airport", "HND Airport", DR, [
        _opt("flight/one-way", "NMI Airport", "HND Airport", cost=410, duration=720,
             fl=_flight_option(price_usd=410, duration_min=720, stops=2,
                               origin_iata="NMI", destination_iata="HND")),
    ])
    ks.update_route("NRT Airport", "Tokyo", ANY, [
        _opt("metro", "NRT Airport", "Tokyo", cost=15, duration=50),
        _opt("taxi",  "NRT Airport", "Tokyo", cost=60, duration=35),
    ])
    ks.update_route("HND Airport", "Tokyo", ANY, [
        _opt("metro", "HND Airport", "Tokyo", cost=10, duration=30),
    ])
    ks.update_route("Delhi", "DEL Airport", ANY, [
        _opt("taxi", "Delhi", "DEL Airport", cost=20, duration=45),
    ])
    return ks


# ---------------------------------------------------------------------------
# specialist.run() — output parsing
# ---------------------------------------------------------------------------

def test_transportation_run_raises_with_details_on_malformed_items():
    bad_json = json.dumps([
        {"mode": "taxi", "origin": "Mumbai", "destination": "BOM Airport"},
        {"mode": "flight/one-way"},  # missing required origin and destination
    ])
    specialist, _ = _make_specialist(stop_msg(bad_json))
    with pytest.raises(ValueError) as exc_info:
        specialist.run([], "")
    msg = str(exc_info.value)
    assert "failed to parse" in msg
    assert "flight/one-way" in msg


# ---------------------------------------------------------------------------
# _bfs_find_path
# ---------------------------------------------------------------------------

def _get_routes_from_edges(edges: list[tuple[str, str, DateRange]]) -> dict[RouteKey, object]:
    """Build a minimal routes dict from (origin, dest, date_range) triples."""
    from models.knowledge_state import RouteKnowledge
    routes = {}
    for origin, dest, dr in edges:
        rk = RouteKey(origin, dest)
        rk_knowledge = RouteKnowledge()
        rk_knowledge.options[dr] = [_opt("taxi", origin, dest, cost=10)]
        routes[rk] = rk_knowledge
    return routes


def test_bfs_find_path_same_node_returns_single_element_path():
    assert _bfs_find_path("A", "A", DR, {}) == ["A"]


def test_bfs_find_path_returns_correct_sequence():
    routes = _get_routes_from_edges([
        ("A", "B", ANY),
        ("B", "C", ANY),
        ("C", "D", ANY),
    ])
    path = _bfs_find_path("A", "D", DR, routes)
    assert path == ["A", "B", "C", "D"]


def test_bfs_find_path_returns_none_when_no_path():
    routes = _get_routes_from_edges([("A", "B", ANY)])
    assert _bfs_find_path("A", "C", DR, routes) is None


def test_bfs_find_path_respects_date_range_any_fallback():
    # Edge stored under ANY should be traversable for any specific date
    routes = _get_routes_from_edges([("A", "B", ANY), ("B", "C", DR)])
    path = _bfs_find_path("A", "C", DR, routes)
    assert path == ["A", "B", "C"]


def test_bfs_find_path_ignores_edges_with_wrong_date():
    # Edge stored under a different specific date should not be traversable
    other_dr = DateRange.from_string("2026-08-01")
    routes = _get_routes_from_edges([("A", "B", other_dr)])
    assert _bfs_find_path("A", "B", DR, routes) is None


# ---------------------------------------------------------------------------
# _select_relevant_route_keys
# ---------------------------------------------------------------------------

def _get_populated_knowledge_state_from_edges(edges: list[tuple[str, str, DateRange, list[TravelOption]]]) -> KnowledgeState:
    ks = KnowledgeState()
    for origin, dest, dr, opts in edges:
        ks.update_route(origin, dest, dr, opts)
    return ks


def _get_edge_with_taxi(origin, dest, dr=ANY):
    return (origin, dest, dr, [_opt("taxi", origin, dest, cost=10)])


def test_select_relevant_forward_reachable_included():
    ks = _get_populated_knowledge_state_from_edges([_get_edge_with_taxi("Mumbai", "BOM"), _get_edge_with_taxi("Delhi", "DEL")])
    keys = _select_relevant_route_keys("Mumbai", "Tokyo", DR, ks)
    assert RouteKey("Mumbai", "BOM") in keys
    assert RouteKey("Delhi", "DEL") not in keys


def test_select_relevant_backward_reachable_included():
    # Ginza → NRT is backward-connected to Tokyo via NRT → Tokyo
    ks = _get_populated_knowledge_state_from_edges([
        _get_edge_with_taxi("NRT", "Tokyo"),
        _get_edge_with_taxi("Ginza", "NRT"),
        _get_edge_with_taxi("Delhi", "DEL"),
    ])
    keys = _select_relevant_route_keys("Mumbai", "Tokyo", DR, ks)
    assert RouteKey("NRT", "Tokyo") in keys
    assert RouteKey("Ginza", "NRT") in keys
    assert RouteKey("Delhi", "DEL") not in keys


def test_select_relevant_orders_closer_edges_first():
    # Mumbai(0) → A(1) → B(2) → Tokyo
    ks = _get_populated_knowledge_state_from_edges([
        _get_edge_with_taxi("Mumbai", "A"),
        _get_edge_with_taxi("A", "B"),
        _get_edge_with_taxi("B", "Tokyo"),
    ])
    keys = _select_relevant_route_keys("Mumbai", "Tokyo", DR, ks)
    positions = {rk: i for i, rk in enumerate(keys)}
    # Mumbai→A is distance 0 from origin; A→B is distance 1; B→Tokyo is distance 0 from dest / 2 from origin
    assert positions[RouteKey("Mumbai", "A")] < positions[RouteKey("A", "B")]
    assert positions[RouteKey("B", "Tokyo")] < positions[RouteKey("A", "B")]


def test_select_relevant_novel_node_preference_when_trimming():
    # Distance 0 from origin: Mumbai→A, Mumbai→B — both fit within limit=3
    # Distance 1: A→C (novel: introduces C), A→D (novel: introduces D), B→A (not novel: B and A already covered)
    # After distance-0 pass covered_nodes = {Mumbai, A, B}; 1 slot left.
    # Novel edges should win over B→A which adds no new nodes.
    ks = _get_populated_knowledge_state_from_edges([
        _get_edge_with_taxi("Mumbai", "A"),
        _get_edge_with_taxi("Mumbai", "B"),
        _get_edge_with_taxi("A", "C"),
        _get_edge_with_taxi("A", "D"),
        _get_edge_with_taxi("B", "A"),  # not novel: both B and A already covered
    ])
    keys = _select_relevant_route_keys("Mumbai", "Tokyo", DR, ks, limit=3)
    assert len(keys) == 3
    assert RouteKey("Mumbai", "A") in keys
    assert RouteKey("Mumbai", "B") in keys
    assert RouteKey("B", "A") not in keys  # known-node edge loses to novel edges
    assert RouteKey("A", "C") in keys or RouteKey("A", "D") in keys


def test_select_relevant_respects_limit():
    ks = _get_populated_knowledge_state_from_edges([_get_edge_with_taxi(f"Mumbai", f"Node{i}") for i in range(15)])
    keys = _select_relevant_route_keys("Mumbai", "Tokyo", DR, ks, limit=5)
    assert len(keys) <= 5


# ---------------------------------------------------------------------------
# _build_route_summary
# ---------------------------------------------------------------------------

def test_build_route_summary_shows_all_parallel_paths():
    ks = _populate_multi_path_ks()
    summary = _build_route_summary(RouteKey("Mumbai", "Tokyo"), DR, ks, is_new=True)
    # Both departure airport options
    assert "Mumbai to BOM Airport" in summary
    assert "Mumbai to NMI Airport" in summary
    # Both arrival airport options
    assert "NRT Airport to Tokyo" in summary
    assert "HND Airport to Tokyo" in summary
    # Unrelated edge excluded
    assert "Delhi" not in summary


def test_build_route_summary_groups_flights_by_mode():
    ks = _populate_multi_path_ks()
    summary = _build_route_summary(RouteKey("Mumbai", "Tokyo"), DR, ks, is_new=True)
    assert "cheapest one-way" in summary
    assert "cheapest return" in summary


def test_build_route_summary_new_vs_cached_tag():
    ks = _populate_multi_path_ks()
    assert "[new]" in _build_route_summary(RouteKey("Mumbai", "Tokyo"), DR, ks, is_new=True)
    assert "[cached]" in _build_route_summary(RouteKey("Mumbai", "Tokyo"), DR, ks, is_new=False)



# ---------------------------------------------------------------------------
# Wrapper pre-firing checks
# ---------------------------------------------------------------------------

def test_transportation_wrapper_bfs_complete_returns_cache_without_calling_specialist():
    ks = KnowledgeState()
    _populate_complete_path(ks, DR)

    wrapper, _, _, llm = _make_wrapper(ks)
    result = wrapper.execute(
        origin="Mumbai", destination="Tokyo", date_range="2026-07-13",
    )
    llm.chat.assert_not_called()
    assert result["status"] == "ok"
    assert "Mumbai" in result["summary"] and "Tokyo" in result["summary"]


def test_transportation_wrapper_bfs_partial_calls_specialist():
    ks = KnowledgeState()
    ks.update_route("Mumbai", "BOM Airport", ANY, [
        _opt("taxi", "Mumbai", "BOM Airport", cost=30),
    ])

    wrapper, _, _, llm = _make_wrapper(ks)
    wrapper.execute(
        origin="Mumbai", destination="Tokyo", date_range="2026-07-13",
    )
    llm.chat.assert_called()


# ---------------------------------------------------------------------------
# Wrapper post-specialist: grouping and update_route
# ---------------------------------------------------------------------------

def test_transportation_wrapper_groups_by_origin_destination_and_updates_route():
    ks = KnowledgeState()
    options = [
        _opt("flight/one-way", "BOM Airport", "NRT Airport", cost=450, fl=_flight_option()),
        _opt("taxi",  "Mumbai", "BOM Airport", cost=30),
        _opt("metro", "NRT Airport", "Tokyo",  cost=15),
    ]
    _, specialist, ks, llm = _make_wrapper(ks)
    llm.chat.return_value = stop_msg(_options_json(options))

    wrapper = TransportationWrapperTool(specialist, ks, UserContext())
    wrapper.execute(origin="Mumbai", destination="Tokyo", date_range="2026-07-13")

    assert DR in ks.routes[RouteKey("BOM Airport", "NRT Airport")].options
    assert ANY in ks.routes[RouteKey("Mumbai", "BOM Airport")].options
    assert ANY in ks.routes[RouteKey("NRT Airport", "Tokyo")].options


def test_transportation_wrapper_exception_returns_error_and_leaves_knowledge_unchanged():
    ks = KnowledgeState()
    _, specialist, ks, _ = _make_wrapper(ks)
    specialist.run = MagicMock(side_effect=RuntimeError("quota exceeded"))

    wrapper = TransportationWrapperTool(specialist, ks, UserContext())
    result = wrapper.execute(
        origin="Mumbai", destination="Tokyo", date_range="2026-07-13",
    )
    assert result["status"] == "error"
    assert "TransportationSpecialist" in result["summary"]
    assert len(ks.routes) == 0


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

def _complete_options() -> list[TravelOption]:
    return [
        _opt("taxi",  "Mumbai", "BOM Airport", cost=30),
        _opt("flight/one-way", "BOM Airport", "NRT Airport", cost=450, fl=_flight_option()),
        _opt("metro", "NRT Airport", "Tokyo",  cost=15),
    ]


def test_wrapper_retries_when_first_attempt_leaves_path_incomplete():
    ks = KnowledgeState()
    _, specialist, ks, llm = _make_wrapper(ks)
    # First call returns nothing; second call returns the complete path
    llm.chat.side_effect = [
        stop_msg(_options_json([])),               # first attempt — no options
        stop_msg(_options_json(_complete_options())),  # retry — complete path
    ]

    wrapper = TransportationWrapperTool(specialist, ks, UserContext())
    result = wrapper.execute(
        origin="Mumbai", destination="Tokyo", date_range="2026-07-13",
    )
    assert result["status"] == "ok"
    # LLM was called more than once (at least 2 specialist iterations)
    assert llm.chat.call_count >= 2


def test_wrapper_returns_failed_when_path_not_found_after_two_attempts():
    ks = KnowledgeState()
    _, specialist, ks, llm = _make_wrapper(ks)
    llm.chat.return_value = stop_msg(_options_json([]))  # both attempts find nothing

    wrapper = TransportationWrapperTool(specialist, ks, UserContext())
    result = wrapper.execute(
        origin="Mumbai", destination="Tokyo", date_range="2026-07-13",
    )
    assert result["status"] == "failed"
    assert "Mumbai" in result["summary"] and "Tokyo" in result["summary"]


def test_wrapper_does_not_retry_when_first_attempt_succeeds():
    ks = KnowledgeState()
    _, specialist, ks, llm = _make_wrapper(ks)
    llm.chat.return_value = stop_msg(_options_json(_complete_options()))

    wrapper = TransportationWrapperTool(specialist, ks, UserContext())
    result = wrapper.execute(
        origin="Mumbai", destination="Tokyo", date_range="2026-07-13",
    )
    assert result["status"] == "ok"
    # Should have stopped after first successful attempt (1 specialist run = 1 LLM call)
    assert llm.chat.call_count == 1
