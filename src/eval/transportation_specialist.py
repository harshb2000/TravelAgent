#!/usr/bin/env python3
"""
Assertion-based evaluation for TransportationSpecialist.

Group A: IATA resolution (multi-airport, re-use, valid codes, no-airport destinations)
Group B: Route completeness (transfers at both endpoints, airport format, round-trip)

Every test makes real LLM, real flight search, and real web search API calls.

Usage (from src/):
    python eval/transportation_specialist.py [filter ...]

Results saved to:
    src/eval/results/transportation_specialist/<timestamp>.json
"""

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from clients.llm_client import LLMClient
from clients.search_client import SearchClient
from clients.serpapi_client import SerpApiClient
from config.settings import settings
from config.specialist_tuning import resolve_model_config
from models.knowledge_state import DateRange, RouteKey, TravelOption
from specialists.transportation import TransportationSpecialist
from tools.flight_search import FlightSearchTool
from tools.web_search import WebSearchTool


_IATA_RE = re.compile(r"^[A-Z]{3}$")
_AIRPORT_FORMAT_RE = re.compile(r".+Airport.+", re.IGNORECASE)
_FLIGHT_MODES = {"flight/one-way", "flight/return"}


def _future_date(days_ahead: int) -> str:
    """ISO date `days_ahead` days from today — keeps eval dates perpetually in the future."""
    return (date.today() + timedelta(days=days_ahead)).isoformat()


# ---------------------------------------------------------------------------
# Run context
# ---------------------------------------------------------------------------

class _Run:
    def __init__(self):
        self.specialist: TransportationSpecialist | None = None
        self.options: list[TravelOption] = []
        self.extras: dict = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm() -> LLMClient:
    return LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        extra_headers=resolve_model_config(settings.llm_model).extra_headers,
    )


def _make_specialist(llm: LLMClient, search_client: SearchClient, serpapi_client: SerpApiClient) -> TransportationSpecialist:
    return TransportationSpecialist(llm, [WebSearchTool(search_client), FlightSearchTool(serpapi_client)])


def _history_messages(specialist: TransportationSpecialist) -> list[dict]:
    return specialist._agent._history.messages


def _get_tool_calls(messages: list[dict], tool_name: str) -> list[dict]:
    return [
        tc
        for msg in messages
        if msg.get("role") == "assistant" and msg.get("tool_calls")
        for tc in msg["tool_calls"]
        if tc["function"]["name"] == tool_name
    ]


def _parse_args(tc: dict) -> dict:
    return json.loads(tc["function"].get("arguments", "{}"))


def _web_queries(messages: list[dict]) -> list[str]:
    return [_parse_args(tc).get("query", "") for tc in _get_tool_calls(messages, "web_search")]


def _is_iata_lookup(query: str, *cities: str) -> bool:
    q = query.lower()
    iata_signal = "iata" in q or "airport code" in q
    city_match = any(city.lower() in q for city in cities)
    return iata_signal and city_match


def _ground_options(options: list[TravelOption]) -> list[TravelOption]:
    return [o for o in options if o.mode not in _FLIGHT_MODES]


def _flight_options(options: list[TravelOption]) -> list[TravelOption]:
    return [o for o in options if o.mode in _FLIGHT_MODES]


# ---------------------------------------------------------------------------
# Result serialization
# ---------------------------------------------------------------------------

def _serialize_turns(messages: list[dict]) -> list[list[dict]]:
    turns = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            turns.append([
                {
                    "name": tc["function"]["name"],
                    "args": json.loads(tc["function"].get("arguments", "{}")),
                }
                for tc in msg["tool_calls"]
            ])
    return turns


def _serialize_options(options: list[TravelOption]) -> list[dict]:
    return [o.model_dump() for o in options]


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_test(fn, llm, search_client, serpapi_client) -> dict:
    name = fn.__name__
    run = _Run()
    try:
        fn(llm, search_client, serpapi_client, run)
        msgs = _history_messages(run.specialist) if run.specialist else []
        return {
            "name": name,
            "passed": True,
            "details": "",
            "turns": _serialize_turns(msgs),
            "options": _serialize_options(run.options),
            **run.extras,
        }
    except AssertionError as e:
        msgs = _history_messages(run.specialist) if run.specialist else []
        return {
            "name": name,
            "passed": False,
            "details": str(e),
            "turns": _serialize_turns(msgs),
            "options": _serialize_options(run.options),
            **run.extras,
        }
    except Exception as e:
        msgs = _history_messages(run.specialist) if run.specialist else []
        return {
            "name": name,
            "passed": False,
            "details": f"EXCEPTION: {type(e).__name__}: {e}",
            "turns": _serialize_turns(msgs),
            "options": _serialize_options(run.options),
            **run.extras,
        }


# ---------------------------------------------------------------------------
# Group A — IATA resolution
# ---------------------------------------------------------------------------

def multi_airport_city_uses_all_relevant_codes(llm, search_client, serpapi_client, run):
    """Bangkok has two major airports (BKK, DMK) — both must appear in flight_search (A1)."""
    run.specialist = _make_specialist(llm, search_client, serpapi_client)
    run.options = run.specialist.run(RouteKey("Delhi", "Bangkok"), DateRange.from_string(_future_date(30)))
    msgs = _history_messages(run.specialist)
    flight_calls = _get_tool_calls(msgs, "flight_search")
    assert flight_calls, "no flight_search call found"
    args = _parse_args(flight_calls[0])
    origins = args.get("origin_airports", [])
    dests = args.get("destination_airports", [])
    run.extras["flight_search_args"] = {"origin_airports": origins, "destination_airports": dests}
    assert "DEL" in origins, f"expected DEL in origin_airports, got {origins}"
    assert "BKK" in dests, f"expected BKK in destination_airports, got {dests}"
    assert "DMK" in dests, f"expected DMK in destination_airports, got {dests}"


def no_iata_re_resolution_when_already_in_history(llm, search_client, serpapi_client, run):
    """IATA codes resolved in a prior call must not be looked up again on the next call (A2).

    Both calls use the same specialist instance so history persists. The second call
    (different date, same city pair) must skip IATA resolution and go straight to
    flight_search with the codes already established.
    """
    run.specialist = _make_specialist(llm, search_client, serpapi_client)

    # First call — seeds BOM/NRT in history
    run.specialist.run(RouteKey("Mumbai", "Tokyo"), DateRange.from_string(_future_date(30)))
    queries_after_first = _web_queries(_history_messages(run.specialist))

    # Second call — same city pair, different date
    run.options = run.specialist.run(RouteKey("Mumbai", "Tokyo"), DateRange.from_string(_future_date(60)))
    queries_after_second = _web_queries(_history_messages(run.specialist))

    new_queries = queries_after_second[len(queries_after_first):]
    run.extras["new_web_queries"] = new_queries

    iata_lookups = [q for q in new_queries if _is_iata_lookup(q, "Mumbai", "Tokyo", "BOM", "NRT")]
    assert not iata_lookups, (
        f"IATA re-resolution detected in second call: {iata_lookups}"
    )

    # Codes should still be correct
    msgs = _history_messages(run.specialist)
    second_call_flights = _get_tool_calls(msgs, "flight_search")
    if second_call_flights:
        args = _parse_args(second_call_flights[-1])
        origins = args.get("origin_airports", [])
        dests = args.get("destination_airports", [])
        assert any(c in {"BOM"} for c in origins), \
            f"expected BOM in second flight_search origins, got {origins}"
        assert any(c in {"NRT", "HND"} for c in dests), \
            f"expected NRT or HND in second flight_search destinations, got {dests}"


def flight_search_uses_valid_iata_codes(llm, search_client, serpapi_client, run):
    """All codes passed to flight_search must match [A-Z]{3} — no city names or lowercase (A3)."""
    run.specialist = _make_specialist(llm, search_client, serpapi_client)
    run.options = run.specialist.run(RouteKey("London", "Paris"), DateRange.from_string(_future_date(30)))
    msgs = _history_messages(run.specialist)
    flight_calls = _get_tool_calls(msgs, "flight_search")
    assert flight_calls, "no flight_search call found"
    all_codes = []
    for tc in flight_calls:
        args = _parse_args(tc)
        all_codes.extend(args.get("origin_airports", []))
        all_codes.extend(args.get("destination_airports", []))
    run.extras["flight_search_codes"] = all_codes
    invalid = [c for c in all_codes if not _IATA_RE.match(c)]
    assert not invalid, f"invalid IATA codes in flight_search args: {invalid}"


def single_airport_city_uses_exactly_one_code(llm, search_client, serpapi_client, run):
    """Singapore (SIN) and Doha (DOH) each have one main airport — no padding with spurious codes (A4)."""
    run.specialist = _make_specialist(llm, search_client, serpapi_client)
    run.options = run.specialist.run(RouteKey("Singapore", "Doha"), DateRange.from_string(_future_date(30)))
    msgs = _history_messages(run.specialist)
    flight_calls = _get_tool_calls(msgs, "flight_search")
    assert flight_calls, "no flight_search call found"
    args = _parse_args(flight_calls[0])
    origins = args.get("origin_airports", [])
    dests = args.get("destination_airports", [])
    run.extras["flight_search_args"] = {"origin_airports": origins, "destination_airports": dests}
    assert origins == ["SIN"], f"expected exactly ['SIN'] for Singapore, got {origins}"
    assert dests == ["DOH"], f"expected exactly ['DOH'] for Doha, got {dests}"


def no_airport_destination_routes_via_gateway_with_onward_transfer(llm, search_client, serpapi_client, run):
    """Mahabaleshwar has no airport — specialist must route via nearest gateway (PNQ/BOM)
    and include a ground TravelOption reaching Mahabaleshwar, not terminating at the gateway (A5)."""
    run.specialist = _make_specialist(llm, search_client, serpapi_client)
    run.options = run.specialist.run(RouteKey("Delhi", "Mahabaleshwar"), DateRange.from_string(_future_date(30)))
    msgs = _history_messages(run.specialist)
    flight_calls = _get_tool_calls(msgs, "flight_search")
    assert flight_calls, "no flight_search call found — expected flight to nearest gateway"
    args = _parse_args(flight_calls[0])
    dests = args.get("destination_airports", [])
    run.extras["flight_search_args"] = {"origin_airports": args.get("origin_airports", []), "destination_airports": dests}
    valid_gateways = {"PNQ", "BOM"}
    assert any(c in valid_gateways for c in dests), (
        f"expected PNQ or BOM as gateway for Mahabaleshwar, got destination_airports={dests}"
    )
    reaches_destination = any(
        "mahabaleshwar" in (o.destination or "").lower()
        for o in run.options
    )
    assert reaches_destination, (
        "no TravelOption with destination 'Mahabaleshwar' found — "
        "path terminates at gateway city without onward ground transfer"
    )


def island_destination_routes_via_mainland_gateway_with_ferry(llm, search_client, serpapi_client, run):
    """Koh Tao has no airport — specialist must route via a mainland gateway and include a
    ferry leg reaching Koh Tao, not terminating at the gateway city (A6)."""
    run.specialist = _make_specialist(llm, search_client, serpapi_client)
    run.options = run.specialist.run(RouteKey("Delhi", "Koh Tao"), DateRange.from_string(_future_date(30)))
    msgs = _history_messages(run.specialist)
    flight_calls = _get_tool_calls(msgs, "flight_search")
    assert flight_calls, "no flight_search call found — expected flight to mainland gateway"
    args = _parse_args(flight_calls[0])
    dests = args.get("destination_airports", [])
    run.extras["flight_search_args"] = {"origin_airports": args.get("origin_airports", []), "destination_airports": dests}
    valid_gateways = {"BKK", "DMK", "URT", "HKT"}
    assert any(c in valid_gateways for c in dests), (
        f"expected one of BKK/DMK/URT/HKT as gateway for Koh Tao, got {dests}"
    )
    ferry_to_island = any(
        o.mode in {"ferry", "boat"} and "koh tao" in (o.destination or "").lower()
        for o in run.options
    )
    assert ferry_to_island, (
        "no ferry TravelOption with destination 'Koh Tao' found — "
        "path must include a ferry leg reaching the island"
    )


# ---------------------------------------------------------------------------
# Group B — Route completeness
# ---------------------------------------------------------------------------

def output_contains_transfers_at_both_city_endpoints(llm, search_client, serpapi_client, run):
    """Full path must include a ground transfer at the departure city and at the arrival city (B1)."""
    run.specialist = _make_specialist(llm, search_client, serpapi_client)
    run.options = run.specialist.run(RouteKey("Mumbai", "Tokyo"), DateRange.from_string(_future_date(30)))
    flight_opts = _flight_options(run.options)
    ground_opts = _ground_options(run.options)
    assert flight_opts, "no flight TravelOption found"
    combined = " ".join((o.origin + " " + o.destination).lower() for o in ground_opts)
    assert "mumbai" in combined, (
        f"no ground transfer touches Mumbai (departure end). "
        f"Ground options: {[(o.origin, o.destination) for o in ground_opts]}"
    )
    assert "tokyo" in combined, (
        f"no ground transfer touches Tokyo (arrival end). "
        f"Ground options: {[(o.origin, o.destination) for o in ground_opts]}"
    )


def flight_options_use_airport_format(llm, search_client, serpapi_client, run):
    """Flight TravelOption origin/destination must follow '<IATA> Airport, <City>' format (B2)."""
    run.specialist = _make_specialist(llm, search_client, serpapi_client)
    run.options = run.specialist.run(RouteKey("Mumbai", "Tokyo"), DateRange.from_string(_future_date(30)))
    flight_opts = _flight_options(run.options)
    assert flight_opts, "no flight TravelOption found"
    bad = []
    for o in flight_opts:
        if not _AIRPORT_FORMAT_RE.match(o.origin):
            bad.append(f"origin='{o.origin}'")
        if not _AIRPORT_FORMAT_RE.match(o.destination):
            bad.append(f"destination='{o.destination}'")
    assert not bad, f"flight options with non-airport format: {bad}"


def round_trip_uses_correct_modes_without_duplicate_ground_transfers(llm, search_client, serpapi_client, run):
    """Round-trip: both legs must be flight/return; ground transfers must not be duplicated (B3)."""
    run.specialist = _make_specialist(llm, search_client, serpapi_client)
    run.options = run.specialist.run(
        RouteKey("Mumbai", "Tokyo"),
        DateRange.from_string(f"{_future_date(30)} to {_future_date(40)}"),
        trip_type="round_trip",
    )
    msgs = _history_messages(run.specialist)
    flight_calls = _get_tool_calls(msgs, "flight_search")
    assert flight_calls, "no flight_search call found"
    first_args = _parse_args(flight_calls[0])
    assert first_args.get("return_date"), (
        "flight_search was not called with return_date — required for round_trip"
    )
    one_way = [o for o in run.options if o.mode == "flight/one-way"]
    assert not one_way, (
        f"found flight/one-way options in a round_trip result: "
        f"{[(o.origin, o.destination) for o in one_way]}"
    )
    return_legs = [o for o in run.options if o.mode == "flight/return"]
    assert len(return_legs) >= 2, (
        f"expected ≥ 2 flight/return options (outbound + return leg), got {len(return_legs)}"
    )
    ground_opts = _ground_options(run.options)
    ground_tuples = [(o.mode, o.origin, o.destination) for o in ground_opts]
    run.extras["ground_transfer_tuples"] = ground_tuples
    duplicates = [t for t in set(ground_tuples) if ground_tuples.count(t) > 1]
    assert not duplicates, (
        f"duplicate ground transfer entries found (each endpoint should appear once): {duplicates}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import datetime as dt

    llm = _make_llm()
    search_client = SearchClient(api_key=settings.tavily_api_key)
    serpapi_client = SerpApiClient(api_key=settings.serpapi_api_key)

    all_tests = [
        multi_airport_city_uses_all_relevant_codes,
        no_iata_re_resolution_when_already_in_history,
        flight_search_uses_valid_iata_codes,
        single_airport_city_uses_exactly_one_code,
        no_airport_destination_routes_via_gateway_with_onward_transfer,
        island_destination_routes_via_mainland_gateway_with_ferry,
        output_contains_transfers_at_both_city_endpoints,
        flight_options_use_airport_format,
        round_trip_uses_correct_modes_without_duplicate_ground_transfers,
    ]

    filters = sys.argv[1:]
    if filters:
        tests = [fn for fn in all_tests if any(f in fn.__name__ for f in filters)]
        if not tests:
            print(f"No tests matched filters: {filters}")
            print("Available tests:")
            for fn in all_tests:
                print(f"  {fn.__name__}")
            return
    else:
        tests = all_tests

    results = []
    for fn in tests:
        print(f"  {fn.__name__} ... ", end="", flush=True)
        result = run_test(fn, llm, search_client, serpapi_client)
        results.append(result)
        print("PASS" if result["passed"] else f"FAIL  {result['details']}")

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n{passed}/{total} passed")

    output = {
        "specialist": "TransportationSpecialist",
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model": settings.llm_model,
        "results": results,
        "summary": {"passed": passed, "failed": total - passed, "total": total},
    }

    results_dir = Path(__file__).parent / "results" / "transportation_specialist"
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = results_dir / f"{ts}.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
