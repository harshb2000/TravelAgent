import json
from unittest.mock import patch, MagicMock

from clients.serpapi_client import SerpApiClient
from models.flights import FlightOption
from tools.flight_search import FlightSearchTool, _top3
from tests.tools.helpers import load_fixture, mock_response

_ORIGIN   = ["BOM", "NMI"]
_DEST     = ["NRT", "HND"]
_DEP_DATE = "2026-07-13"
_RET_DATE = "2026-07-23"


def _tool():
    return FlightSearchTool(SerpApiClient(api_key="test-key"))


# ---------------------------------------------------------------------------
# One-way — basic
# ---------------------------------------------------------------------------

def test_flight_search_returns_flight_details():
    fixture = load_fixture("serpapi_flights_bom_nrt.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(fixture)
        result = _tool().execute(
            origin_airports=_ORIGIN, destination_airports=_DEST, departure_date=_DEP_DATE
        )
    assert result["trip_type"] == "one_way"
    assert "outbound" in result
    options = result["outbound"]["options"]
    assert 1 <= len(options) <= 3
    for field in ("airline", "flight_number", "price_usd", "stops", "duration_min",
                  "departure", "arrival", "origin_iata", "destination_iata"):
        assert field in options[0]


def test_flight_search_stops_derived_from_segments():
    fixture = load_fixture("serpapi_flights_bom_nrt.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(fixture)
        result = _tool().execute(
            origin_airports=_ORIGIN, destination_airports=_DEST, departure_date=_DEP_DATE
        )
    for option in result["outbound"]["options"]:
        assert option["stops"] >= 0


def test_flight_search_joins_airport_lists():
    fixture = load_fixture("serpapi_flights_bom_nrt.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(fixture)
        _tool().execute(
            origin_airports=_ORIGIN, destination_airports=_DEST, departure_date=_DEP_DATE
        )
    params = mock_get.call_args[1]["params"]
    assert params["departure_id"] == "BOM,NMI"
    assert params["arrival_id"] == "NRT,HND"


def test_flight_search_one_way_sends_type_2():
    fixture = load_fixture("serpapi_flights_bom_nrt.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(fixture)
        _tool().execute(
            origin_airports=_ORIGIN, destination_airports=_DEST, departure_date=_DEP_DATE
        )
    params = mock_get.call_args[1]["params"]
    assert params["type"] == "2"
    assert "return_date" not in params


# ---------------------------------------------------------------------------
# Top-3 selection
# ---------------------------------------------------------------------------

def _make_flight(airline: str, price: float, duration: int, stops: int) -> FlightOption:
    return FlightOption(
        airline=airline, flight_number=f"{airline[:2]}1",
        price_usd=price, stops=stops, duration_min=duration,
        departure="2026-07-13 08:00", arrival="2026-07-13 20:00",
        origin_iata="BOM", destination_iata="NRT",
    )


def test_top3_returns_all_when_three_or_fewer():
    flights = [_make_flight("AI", 300.0, 600, 0), _make_flight("EK", 400.0, 500, 1)]
    assert _top3(flights) == flights


def test_top3_selects_min_cost_min_duration_min_stops():
    # Four distinct flights; cheapest ≠ fastest ≠ fewest-stops
    flights = [
        _make_flight("A", 200.0, 1200, 2),   # min-cost
        _make_flight("B", 400.0, 400, 1),    # min-duration
        _make_flight("C", 350.0, 800, 0),    # min-stops
        _make_flight("D", 250.0, 1000, 2),   # next-cheapest (not selected — already 3)
    ]
    selected = _top3(flights)
    assert len(selected) == 3
    prices    = {o.price_usd    for o in selected}
    durations = {o.duration_min for o in selected}
    stops_set = {o.stops        for o in selected}
    assert 200.0 in prices    # cheapest
    assert 400   in durations  # fastest
    assert 0     in stops_set  # fewest stops


def test_top3_fills_remaining_when_overlap():
    # When cheapest == fastest, only 2 distinct → fill with next-cheapest
    flights = [
        _make_flight("A", 200.0, 400, 2),   # min-cost AND min-duration
        _make_flight("B", 350.0, 800, 0),   # min-stops
        _make_flight("C", 300.0, 900, 1),   # next-cheapest filler
        _make_flight("D", 500.0, 700, 1),   # not selected
    ]
    selected = _top3(flights)
    assert len(selected) == 3
    prices = {o.price_usd for o in selected}
    assert 200.0 in prices
    assert 300.0 in prices  # filler
    assert 350.0 in prices


def test_flight_search_top3_total_found():
    fixture = load_fixture("serpapi_flights_bom_nrt.json")
    priced = [f for f in fixture["best_flights"] + fixture["other_flights"] if "price" in f]
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(fixture)
        result = _tool().execute(
            origin_airports=_ORIGIN, destination_airports=_DEST, departure_date=_DEP_DATE
        )
    assert result["outbound"]["total_found"] == len(priced)
    assert len(result["outbound"]["options"]) <= 3


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

def test_flight_search_round_trip_makes_two_calls_and_returns_both_legs():
    rt_outbound = load_fixture("serpapi_flights_roundtrip.json")
    rt_return   = load_fixture("serpapi_flights_roundtrip_return.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.side_effect = [mock_response(rt_outbound), mock_response(rt_return)]
        result = _tool().execute(
            origin_airports=_ORIGIN, destination_airports=_DEST,
            departure_date=_DEP_DATE, return_date=_RET_DATE,
        )
    assert mock_get.call_count == 2
    assert result["trip_type"] == "round_trip"
    assert "outbound" in result
    assert "return_leg" in result and result["return_leg"] is not None
    assert "note" in result


def test_flight_search_round_trip_second_call_uses_first_available_outbound_token():
    rt_outbound = load_fixture("serpapi_flights_roundtrip.json")
    rt_return   = load_fixture("serpapi_flights_roundtrip_return.json")
    first_token = (rt_outbound["best_flights"] + rt_outbound["other_flights"])[0]["departure_token"]
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.side_effect = [mock_response(rt_outbound), mock_response(rt_return)]
        _tool().execute(
            origin_airports=_ORIGIN, destination_airports=_DEST,
            departure_date=_DEP_DATE, return_date=_RET_DATE,
        )
    assert mock_get.call_args_list[1][1]["params"]["departure_token"] == first_token


def test_flight_search_round_trip_partial_when_no_departure_token():
    rt_outbound = load_fixture("serpapi_flights_roundtrip.json")
    no_token = json.loads(json.dumps(rt_outbound))
    for f in no_token.get("best_flights", []) + no_token.get("other_flights", []):
        f.pop("departure_token", None)
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(no_token)
        result = _tool().execute(
            origin_airports=_ORIGIN, destination_airports=_DEST,
            departure_date=_DEP_DATE, return_date=_RET_DATE,
        )
    assert mock_get.call_count == 1
    assert result["status"] == "partial"
    assert "departure token" in result["note"].lower()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_flight_search_round_trip_return_must_be_after_departure():
    result = _tool().execute(
        origin_airports=_ORIGIN, destination_airports=_DEST,
        departure_date="2026-07-23", return_date="2026-07-13",
    )
    assert result["status"] == "error"


def test_flight_search_invalid_departure_date_format():
    result = _tool().execute(
        origin_airports=_ORIGIN, destination_airports=_DEST,
        departure_date="13-07-2026",
    )
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_flight_search_429_returns_error():
    error_resp = MagicMock()
    error_resp.status_code = 429
    error_resp.json.return_value = {"error": "your account has run out of searches"}
    with patch("clients.serpapi_client.httpx.get", return_value=error_resp):
        result = _tool().execute(
            origin_airports=_ORIGIN, destination_airports=_DEST, departure_date=_DEP_DATE
        )
    assert result["status"] == "error"
    assert "quota" in result["error"].lower() or "searches" in result["error"].lower()
    assert "fallback" in result


def test_flight_search_empty_results_returns_error():
    empty = {"best_flights": [], "other_flights": [], "_fixture_meta": {}}
    with patch("clients.serpapi_client.httpx.get", return_value=mock_response(empty)):
        result = _tool().execute(
            origin_airports=_ORIGIN, destination_airports=_DEST, departure_date=_DEP_DATE
        )
    assert result["status"] == "error"
    assert "no flights" in result["error"].lower()
    assert "fallback" in result
