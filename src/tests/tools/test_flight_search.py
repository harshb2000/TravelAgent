import json
from unittest.mock import patch, MagicMock

from clients.serpapi_client import SerpApiClient
from tools.flight_search import FlightSearchTool
from tests.tools.helpers import load_fixture, mock_response

_ONE_WAY_LEG = {"origin_airports": ["BOM", "NMI"], "destination_airports": ["NRT", "HND"], "date": "2026-07-13"}
_RT_LEGS = [
    {"origin_airports": ["BOM", "NMI"], "destination_airports": ["NRT", "HND"], "date": "2026-07-13"},
    {"origin_airports": ["NRT", "HND"], "destination_airports": ["BOM", "NMI"], "date": "2026-07-23"},
]
_MC_LEGS = [
    {"origin_airports": ["BOM", "NMI"], "destination_airports": ["NRT", "HND"], "date": "2026-07-13"},
    {"origin_airports": ["NRT", "HND"], "destination_airports": ["DEL"],         "date": "2026-07-20"},
]


def _tool():
    return FlightSearchTool(SerpApiClient(api_key="test-key"))


def test_flight_search_returns_flight_details():
    fixture = load_fixture("serpapi_flights_bom_nrt.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(fixture)
        result = _tool().execute(trip_type="one_way", legs=[_ONE_WAY_LEG])
    assert result["trip_type"] == "one_way"
    assert len(result["legs"]) == 1
    leg = result["legs"][0]
    assert leg["leg"] == 1
    assert leg["origin"] == "BOM,NMI"
    assert leg["destination"] == "NRT,HND"
    priced = [f for f in fixture["best_flights"] + fixture["other_flights"] if "price" in f]
    assert len(leg["options"]) == len(priced)
    f0 = leg["options"][0]
    for field in ("airline", "flight_number", "price_usd", "stops", "duration_min",
                  "departure", "arrival", "origin_iata", "destination_iata"):
        assert field in f0
    assert "_departure_token" not in f0
    assert "departure_token" not in f0


def test_flight_search_stops_derived_from_segments():
    fixture = load_fixture("serpapi_flights_bom_nrt.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(fixture)
        result = _tool().execute(trip_type="one_way", legs=[_ONE_WAY_LEG])
    priced = [f for f in fixture["best_flights"] + fixture["other_flights"] if "price" in f]
    for i, flight in enumerate(result["legs"][0]["options"]):
        assert flight["stops"] == len(priced[i]["flights"]) - 1


def test_flight_search_joins_airport_lists():
    fixture = load_fixture("serpapi_flights_bom_nrt.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(fixture)
        _tool().execute(trip_type="one_way", legs=[_ONE_WAY_LEG])
    params = mock_get.call_args[1]["params"]
    assert params["departure_id"] == "BOM,NMI"
    assert params["arrival_id"] == "NRT,HND"


def test_flight_search_one_way_sends_type_2():
    fixture = load_fixture("serpapi_flights_bom_nrt.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(fixture)
        _tool().execute(trip_type="one_way", legs=[_ONE_WAY_LEG])
    params = mock_get.call_args[1]["params"]
    assert params["type"] == "2"
    assert "return_date" not in params


def test_flight_search_round_trip_makes_two_calls_and_returns_both_legs():
    rt_outbound = load_fixture("serpapi_flights_roundtrip.json")
    rt_return   = load_fixture("serpapi_flights_roundtrip_return.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.side_effect = [mock_response(rt_outbound), mock_response(rt_return)]
        result = _tool().execute(trip_type="round_trip", legs=_RT_LEGS)
    assert mock_get.call_count == 2
    assert result["trip_type"] == "round_trip"
    assert len(result["legs"]) == 2
    assert result["legs"][0]["origin"] == "BOM,NMI"
    assert result["legs"][1]["origin"] == "NRT,HND"
    assert "note" in result
    for leg in result["legs"]:
        for f in leg["options"]:
            assert "departure_token" not in f
            assert "_departure_token" not in f


def test_flight_search_round_trip_second_call_uses_first_available_outbound_token():
    rt_outbound = load_fixture("serpapi_flights_roundtrip.json")
    rt_return   = load_fixture("serpapi_flights_roundtrip_return.json")
    first_token = (rt_outbound["best_flights"] + rt_outbound["other_flights"])[0]["departure_token"]
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.side_effect = [mock_response(rt_outbound), mock_response(rt_return)]
        _tool().execute(trip_type="round_trip", legs=_RT_LEGS)
    assert mock_get.call_args_list[1][1]["params"]["departure_token"] == first_token


def test_flight_search_multi_city_makes_one_call_per_leg():
    mc_leg1 = load_fixture("serpapi_flights_multicity.json")
    mc_leg2 = load_fixture("serpapi_flights_multicity_leg2.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.side_effect = [mock_response(mc_leg1), mock_response(mc_leg2)]
        result = _tool().execute(trip_type="multi_city", legs=_MC_LEGS)
    assert mock_get.call_count == 2
    assert result["trip_type"] == "multi_city"
    assert len(result["legs"]) == 2


def test_flight_search_multi_city_leg2_uses_first_available_leg1_token():
    mc_leg1 = load_fixture("serpapi_flights_multicity.json")
    mc_leg2 = load_fixture("serpapi_flights_multicity_leg2.json")
    first_token = (mc_leg1["best_flights"] + mc_leg1["other_flights"])[0]["departure_token"]
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.side_effect = [mock_response(mc_leg1), mock_response(mc_leg2)]
        _tool().execute(trip_type="multi_city", legs=_MC_LEGS)
    assert mock_get.call_args_list[1][1]["params"]["departure_token"] == first_token


def test_flight_search_multi_city_uses_multi_city_json():
    mc_leg1 = load_fixture("serpapi_flights_multicity.json")
    mc_leg2 = load_fixture("serpapi_flights_multicity_leg2.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.side_effect = [mock_response(mc_leg1), mock_response(mc_leg2)]
        _tool().execute(trip_type="multi_city", legs=_MC_LEGS)
    params = mock_get.call_args_list[0][1]["params"]
    assert params["type"] == "3"
    legs_sent = json.loads(params["multi_city_json"])
    assert legs_sent[0]["departure_id"] == "BOM,NMI"
    assert legs_sent[1]["departure_id"] == "NRT,HND"


def test_flight_search_multi_city_partial_when_chain_breaks():
    mc_leg1 = load_fixture("serpapi_flights_multicity.json")
    partial_leg1 = json.loads(json.dumps(mc_leg1))
    for f in partial_leg1.get("best_flights", []) + partial_leg1.get("other_flights", []):
        f.pop("departure_token", None)
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(partial_leg1)
        result = _tool().execute(trip_type="multi_city", legs=_MC_LEGS)
    assert mock_get.call_count == 1
    assert result["status"] == "partial"
    assert result["legs_requested"] == 2
    assert result["legs_fetched"] == 1
    assert "incomplete" in result["note"].lower()


def test_flight_search_multi_city_ok_status_when_all_legs_fetched():
    mc_leg1 = load_fixture("serpapi_flights_multicity.json")
    mc_leg2 = load_fixture("serpapi_flights_multicity_leg2.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.side_effect = [mock_response(mc_leg1), mock_response(mc_leg2)]
        result = _tool().execute(trip_type="multi_city", legs=_MC_LEGS)
    assert result.get("status", "ok") == "ok"
    assert result.get("legs_requested") is None


def test_flight_search_round_trip_partial_when_no_departure_token():
    rt_outbound = load_fixture("serpapi_flights_roundtrip.json")
    no_token = json.loads(json.dumps(rt_outbound))
    for f in no_token.get("best_flights", []) + no_token.get("other_flights", []):
        f.pop("departure_token", None)
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(no_token)
        result = _tool().execute(trip_type="round_trip", legs=_RT_LEGS)
    assert mock_get.call_count == 1
    assert result["status"] == "partial"
    assert "departure token" in result["note"].lower()


def test_flight_search_validation_one_way_rejects_two_legs():
    result = _tool().execute(trip_type="one_way", legs=[_ONE_WAY_LEG, _ONE_WAY_LEG])
    assert result["status"] == "error"
    assert "1 leg" in result["error"]


def test_flight_search_validation_round_trip_rejects_one_leg():
    result = _tool().execute(trip_type="round_trip", legs=[_ONE_WAY_LEG])
    assert result["status"] == "error"
    assert "2 legs" in result["error"]


def test_flight_search_validation_round_trip_rejects_three_legs():
    result = _tool().execute(trip_type="round_trip", legs=[_ONE_WAY_LEG, _RT_LEGS[1], _MC_LEGS[1]])
    assert result["status"] == "error"
    assert "2 legs" in result["error"]


def test_flight_search_validation_multi_city_rejects_one_leg():
    result = _tool().execute(trip_type="multi_city", legs=[_ONE_WAY_LEG])
    assert result["status"] == "error"
    assert "2 legs" in result["error"] or "at least" in result["error"]


def test_flight_search_validation_dates_must_be_increasing():
    result = _tool().execute(trip_type="round_trip", legs=[
        {"origin_airports": ["BOM"], "destination_airports": ["NRT"], "date": "2026-07-20"},
        {"origin_airports": ["NRT"], "destination_airports": ["BOM"], "date": "2026-07-13"},
    ])
    assert result["status"] == "error"


def test_flight_search_validation_same_date_rejected():
    result = _tool().execute(trip_type="round_trip", legs=[
        {"origin_airports": ["BOM"], "destination_airports": ["NRT"], "date": "2026-07-13"},
        {"origin_airports": ["NRT"], "destination_airports": ["BOM"], "date": "2026-07-13"},
    ])
    assert result["status"] == "error"


def test_flight_search_validation_invalid_date_format():
    result = _tool().execute(trip_type="one_way", legs=[
        {"origin_airports": ["BOM"], "destination_airports": ["NRT"], "date": "13-07-2026"}
    ])
    assert result["status"] == "error"


def test_flight_search_429_returns_error():
    error_resp = MagicMock()
    error_resp.status_code = 429
    error_resp.json.return_value = {"error": "your account has run out of searches"}
    with patch("clients.serpapi_client.httpx.get", return_value=error_resp):
        result = _tool().execute(trip_type="one_way", legs=[
            {"origin_airports": ["BOM"], "destination_airports": ["NRT"], "date": "2026-07-13"}
        ])
    assert result["status"] == "error"
    assert "quota" in result["error"].lower() or "searches" in result["error"].lower()
    assert "fallback" in result


def test_flight_search_empty_results_returns_error():
    empty = {"best_flights": [], "other_flights": [], "_fixture_meta": {}}
    with patch("clients.serpapi_client.httpx.get", return_value=mock_response(empty)):
        result = _tool().execute(trip_type="one_way", legs=[
            {"origin_airports": ["BOM"], "destination_airports": ["NRT"], "date": "2026-07-13"}
        ])
    assert result["status"] == "error"
    assert "no flights" in result["error"].lower()
    assert "fallback" in result
