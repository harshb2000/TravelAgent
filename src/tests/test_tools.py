import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from clients.weather_client import WeatherClient
from clients.currency_client import CurrencyClient
from clients.search_client import SearchClient
from clients.serpapi_client import SerpApiClient
from tools.weather_forecast import WeatherForecastTool
from tools.climate_summary import ClimateSummaryTool
from tools.currency_convert import CurrencyConvertTool
from tools.web_search import WebSearchTool
from tools.flight_search import FlightSearchTool
from tools.calculate import CalculateTool
from tools.file_write import FileWriteTool

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


def _mock_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data
    return resp


GEO_TOKYO = {
    "results": [{"latitude": 35.6895, "longitude": 139.69171, "timezone": "Asia/Tokyo"}]
}
GEO_EMPTY = {"results": []}


# ---------------------------------------------------------------------------
# WeatherForecastTool
# ---------------------------------------------------------------------------

def test_forecast_tool_returns_per_day_temps_and_descriptions():
    forecast_fixture = _load("openmeteo_forecast_tokyo.json")
    with patch("clients.weather_client.httpx.get") as mock_get:
        mock_get.side_effect = [_mock_response(GEO_TOKYO), _mock_response(forecast_fixture)]
        tool = WeatherForecastTool(WeatherClient())
        result = tool.execute(city="Tokyo", start_date="2026-05-14", end_date="2026-05-20")

    assert result["mode"] == "forecast"
    assert result["city"] == "Tokyo"
    days = result["days"]
    assert len(days) == 7

    day0 = days[0]
    assert day0["date"] == forecast_fixture["daily"]["time"][0]
    assert day0["temp_max"] == forecast_fixture["daily"]["temperature_2m_max"][0]
    assert day0["temp_min"] == forecast_fixture["daily"]["temperature_2m_min"][0]
    assert day0["precipitation_prob"] == forecast_fixture["daily"]["precipitation_probability_max"][0]
    assert day0["precipitation_sum"] is None
    # weathercode 51 → drizzle
    assert "drizzle" in day0["weather_description"].lower()


def test_forecast_tool_geocoding_failure_returns_error():
    with patch("clients.weather_client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(GEO_EMPTY)
        tool = WeatherForecastTool(WeatherClient())
        result = tool.execute(city="Nowhere", start_date="2026-06-01", end_date="2026-06-07")

    assert result["status"] == "error"
    assert "geocod" in result["error"].lower() or "not found" in result["error"].lower()


def test_forecast_tool_geocode_cached_on_second_call():
    forecast_fixture = _load("openmeteo_forecast_tokyo.json")
    with patch("clients.weather_client.httpx.get") as mock_get:
        mock_get.side_effect = [
            _mock_response(GEO_TOKYO), _mock_response(forecast_fixture),
            # second execute: geocode should be cached — only forecast call goes out
            _mock_response(forecast_fixture),
        ]
        client = WeatherClient()
        tool = WeatherForecastTool(client)
        tool.execute(city="Tokyo", start_date="2026-05-14", end_date="2026-05-20")
        tool.execute(city="Tokyo", start_date="2026-05-21", end_date="2026-05-27")

    # 3 total calls: geo + forecast + forecast (no second geo)
    assert mock_get.call_count == 3


# ---------------------------------------------------------------------------
# ClimateSummaryTool
# ---------------------------------------------------------------------------

def test_climate_tool_returns_mode_city_and_days():
    climate_fixture = _load("openmeteo_climate_tokyo_june.json")
    with patch("clients.weather_client.httpx.get") as mock_get:
        mock_get.side_effect = [_mock_response(GEO_TOKYO), _mock_response(climate_fixture)]
        tool = ClimateSummaryTool(WeatherClient())
        result = tool.execute(city="Tokyo", month="June", year=2026)

    assert result["mode"] == "climate"
    assert result["city"] == "Tokyo"
    assert "note" not in result       # note moved to tool description, not output
    assert "month" not in result      # month is derivable from days[0].date
    assert len(result["days"]) == 30


def test_climate_tool_day_shape():
    climate_fixture = _load("openmeteo_climate_tokyo_june.json")
    with patch("clients.weather_client.httpx.get") as mock_get:
        mock_get.side_effect = [_mock_response(GEO_TOKYO), _mock_response(climate_fixture)]
        tool = ClimateSummaryTool(WeatherClient())
        result = tool.execute(city="Tokyo", month="June", year=2026)

    day0 = result["days"][0]
    assert day0["date"] == climate_fixture["daily"]["time"][0]
    assert day0["temp_max"] == climate_fixture["daily"]["temperature_2m_max"][0]
    assert day0["temp_min"] == climate_fixture["daily"]["temperature_2m_min"][0]
    # Climate data carries raw precipitation_sum, not a probability or description
    assert day0["precipitation_prob"] is None
    assert day0["precipitation_sum"] == climate_fixture["daily"]["precipitation_sum"][0]
    assert day0["weather_description"] == ""


def test_weather_and_climate_tools_share_output_schema():
    from tools.weather_forecast import WeatherForecastTool
    from clients.weather_client import WeatherClient
    forecast_schema = WeatherForecastTool(WeatherClient()).to_llm_definition()["function"]["description"]
    climate_schema  = ClimateSummaryTool(WeatherClient()).to_llm_definition()["function"]["description"]
    # Both tools advertise identical output schema
    import re
    def extract_schema(desc):
        m = re.search(r"Success output schema: (.+)\nOn error:", desc, re.DOTALL)
        return m.group(1) if m else ""
    assert extract_schema(forecast_schema) == extract_schema(climate_schema)


def test_climate_tool_geocoding_failure_returns_error():
    with patch("clients.weather_client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(GEO_EMPTY)
        tool = ClimateSummaryTool(WeatherClient())
        result = tool.execute(city="Nowhere", month="June")

    assert result["status"] == "error"


def test_climate_tool_accepts_month_as_number():
    climate_fixture = _load("openmeteo_climate_tokyo_june.json")
    with patch("clients.weather_client.httpx.get") as mock_get:
        mock_get.side_effect = [_mock_response(GEO_TOKYO), _mock_response(climate_fixture)]
        tool = ClimateSummaryTool(WeatherClient())
        result = tool.execute(city="Tokyo", month="6", year=2026)

    assert result["mode"] == "climate"
    assert len(result["days"]) == 30


# ---------------------------------------------------------------------------
# CurrencyConvertTool
# ---------------------------------------------------------------------------

def test_currency_convert_returns_correct_amounts_for_multiple_currencies():
    fixture = _load("frankfurter_usd_rates.json")
    with patch("clients.currency_client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(fixture)
        tool = CurrencyConvertTool(CurrencyClient())
        result = tool.execute(amount=100.0, from_currency="USD", to_currencies=["INR", "EUR"])

    assert result["from_currency"] == "USD"
    assert result["amount"] == 100.0
    inr = result["conversions"]["INR"]
    eur = result["conversions"]["EUR"]
    assert inr["rate"] == fixture["rates"]["INR"]
    assert abs(inr["converted"] - 100.0 * fixture["rates"]["INR"]) < 0.01
    assert eur["rate"] == fixture["rates"]["EUR"]
    assert abs(eur["converted"] - 100.0 * fixture["rates"]["EUR"]) < 0.01


def test_currency_convert_single_http_call_for_all_requested_currencies():
    fixture = _load("frankfurter_usd_rates.json")
    with patch("clients.currency_client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(fixture)
        tool = CurrencyConvertTool(CurrencyClient())
        tool.execute(amount=100.0, from_currency="USD", to_currencies=["INR", "EUR", "GBP", "JPY"])

    # All four currencies fetched in one HTTP call
    assert mock_get.call_count == 1


def test_currency_convert_cached_currencies_not_refetched():
    fixture = _load("frankfurter_usd_rates.json")
    fixture_thb = {"amount": 1.0, "base": "USD", "date": fixture["date"], "rates": {"THB": 34.5}}
    with patch("clients.currency_client.httpx.get") as mock_get:
        mock_get.side_effect = [_mock_response(fixture), _mock_response(fixture_thb)]
        client = CurrencyClient()
        tool = CurrencyConvertTool(client)
        # First call fetches INR, EUR
        tool.execute(amount=100.0, from_currency="USD", to_currencies=["INR", "EUR"])
        # Second call: INR already cached, only THB is missing → one more HTTP call for THB only
        tool.execute(amount=100.0, from_currency="USD", to_currencies=["INR", "THB"])

    assert mock_get.call_count == 2
    # Verify THB conversion used the second fixture
    # (implicitly verified by no error; explicit rate check below)
    result = tool.execute(amount=10.0, from_currency="USD", to_currencies=["THB"])
    assert result["conversions"]["THB"]["rate"] == 34.5


def test_currency_convert_different_base_currencies_each_fetch():
    fixture_usd = _load("frankfurter_usd_rates.json")
    fixture_eur = {"amount": 1.0, "base": "EUR", "date": fixture_usd["date"], "rates": {"INR": 112.0}}
    with patch("clients.currency_client.httpx.get") as mock_get:
        mock_get.side_effect = [_mock_response(fixture_usd), _mock_response(fixture_eur)]
        client = CurrencyClient()
        tool = CurrencyConvertTool(client)
        tool.execute(amount=100.0, from_currency="USD", to_currencies=["INR"])
        tool.execute(amount=100.0, from_currency="EUR", to_currencies=["INR"])

    # Different base currencies → two HTTP calls
    assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------

def test_web_search_returns_formatted_results():
    fixture = _load("tavily_destination_tokyo.json")
    with patch("clients.search_client.TavilyClient") as MockTavily:
        MockTavily.return_value.search.return_value = fixture
        tool = WebSearchTool(SearchClient(api_key="test-key"))
        result = tool.execute(query="Tokyo travel tips 2026 daily budget", depth="advanced")

    assert "results" in result
    assert len(result["results"]) == len(fixture["results"])
    r0 = result["results"][0]
    assert r0["title"] == fixture["results"][0]["title"]
    assert r0["url"] == fixture["results"][0]["url"]
    assert r0["content"] == fixture["results"][0]["content"]
    assert r0["score"] == fixture["results"][0]["score"]


def test_web_search_includes_answer_when_present():
    fixture = _load("tavily_destination_tokyo.json")
    with patch("clients.search_client.TavilyClient") as MockTavily:
        MockTavily.return_value.search.return_value = fixture
        tool = WebSearchTool(SearchClient(api_key="test-key"))
        result = tool.execute(query="Tokyo travel tips 2026 daily budget", depth="advanced")

    assert "answer" in result
    assert result["answer"] == fixture["answer"]


def test_web_search_call_counter_increments():
    fixture = _load("tavily_visa_japan.json")
    with patch("clients.search_client.TavilyClient") as MockTavily:
        MockTavily.return_value.search.return_value = fixture
        client = SearchClient(api_key="test-key")
        tool = WebSearchTool(client)
        tool.execute(query="visa requirements Japan Indian passport 2026")
        tool.execute(query="best time to visit Tokyo weather seasons")

    assert client.call_count == 2


def test_web_search_passes_depth_and_max_results_to_client():
    fixture = _load("tavily_timing_tokyo.json")
    with patch("clients.search_client.TavilyClient") as MockTavily:
        mock_search = MockTavily.return_value.search
        mock_search.return_value = fixture
        tool = WebSearchTool(SearchClient(api_key="test-key"))
        tool.execute(query="best time to visit Tokyo", depth="advanced", max_results=3)

    _, kwargs = mock_search.call_args
    assert kwargs.get("search_depth") == "advanced"
    assert kwargs.get("max_results") == 3


# ---------------------------------------------------------------------------
# BaseTool output_description
# ---------------------------------------------------------------------------

def test_tool_output_model_schema_appended_to_llm_definition():
    from tools.calculate import CalculateTool
    defn = CalculateTool().to_llm_definition()
    desc = defn["function"]["description"]
    assert "Success output schema:" in desc
    # Pydantic-generated schema includes field descriptions
    assert "result" in desc
    assert "label" in desc


def test_tool_without_output_model_has_clean_description():
    from tools.base import BaseTool
    class _Bare(BaseTool):
        name = "bare"
        description = "A bare tool."
        parameters = {"type": "object", "properties": {}, "required": []}
        def execute(self, **kwargs): return {}
    defn = _Bare().to_llm_definition()
    assert "Success output schema:" not in defn["function"]["description"]


# ---------------------------------------------------------------------------
# FlightSearchTool
# ---------------------------------------------------------------------------

_ONE_WAY_LEG = {"origin_airports": ["BOM", "NMI"], "destination_airports": ["NRT", "HND"], "date": "2026-07-13"}
_RT_LEGS = [
    {"origin_airports": ["BOM", "NMI"], "destination_airports": ["NRT", "HND"], "date": "2026-07-13"},
    {"origin_airports": ["NRT", "HND"], "destination_airports": ["BOM", "NMI"], "date": "2026-07-23"},
]
_MC_LEGS = [
    {"origin_airports": ["BOM", "NMI"], "destination_airports": ["NRT", "HND"], "date": "2026-07-13"},
    {"origin_airports": ["NRT", "HND"], "destination_airports": ["DEL"],          "date": "2026-07-20"},
]


def test_flight_search_returns_flight_details():
    fixture = _load("serpapi_flights_bom_nrt.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(fixture)
        tool = FlightSearchTool(SerpApiClient(api_key="test-key"))
        result = tool.execute(trip_type="one_way", legs=[_ONE_WAY_LEG])

    assert result["trip_type"] == "one_way"
    assert len(result["legs"]) == 1
    leg = result["legs"][0]
    assert leg["leg"] == 1
    assert leg["origin"] == "BOM,NMI"
    assert leg["destination"] == "NRT,HND"

    priced = [f for f in fixture["best_flights"] + fixture["other_flights"] if "price" in f]
    assert len(leg["options"]) == len(priced)

    f0 = leg["options"][0]
    assert "airline" in f0
    assert "flight_number" in f0
    assert "price_usd" in f0
    assert "stops" in f0
    assert "duration_min" in f0
    assert "departure" in f0
    assert "arrival" in f0
    assert "origin_iata" in f0
    assert "destination_iata" in f0
    assert "_departure_token" not in f0
    assert "departure_token" not in f0


def test_flight_search_stops_derived_from_segments():
    fixture = _load("serpapi_flights_bom_nrt.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(fixture)
        tool = FlightSearchTool(SerpApiClient(api_key="test-key"))
        result = tool.execute(trip_type="one_way", legs=[_ONE_WAY_LEG])

    priced = [f for f in fixture["best_flights"] + fixture["other_flights"] if "price" in f]
    for i, flight in enumerate(result["legs"][0]["options"]):
        assert flight["stops"] == len(priced[i]["flights"]) - 1, f"flight {i}: wrong stop count"


def test_flight_search_joins_airport_lists():
    fixture = _load("serpapi_flights_bom_nrt.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(fixture)
        FlightSearchTool(SerpApiClient(api_key="test-key")).execute(trip_type="one_way", legs=[_ONE_WAY_LEG])

    params = mock_get.call_args[1]["params"]
    assert params["departure_id"] == "BOM,NMI"
    assert params["arrival_id"] == "NRT,HND"


def test_flight_search_one_way_sends_type_2():
    fixture = _load("serpapi_flights_bom_nrt.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(fixture)
        FlightSearchTool(SerpApiClient(api_key="test-key")).execute(trip_type="one_way", legs=[_ONE_WAY_LEG])

    params = mock_get.call_args[1]["params"]
    assert params["type"] == "2"
    assert "return_date" not in params


def test_flight_search_round_trip_makes_two_calls_and_returns_both_legs():
    rt_outbound = _load("serpapi_flights_roundtrip.json")
    rt_return   = _load("serpapi_flights_roundtrip_return.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.side_effect = [_mock_response(rt_outbound), _mock_response(rt_return)]
        result = FlightSearchTool(SerpApiClient(api_key="test-key")).execute(trip_type="round_trip", legs=_RT_LEGS)

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
    rt_outbound = _load("serpapi_flights_roundtrip.json")
    rt_return   = _load("serpapi_flights_roundtrip_return.json")
    first_token = (rt_outbound["best_flights"] + rt_outbound["other_flights"])[0]["departure_token"]
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.side_effect = [_mock_response(rt_outbound), _mock_response(rt_return)]
        FlightSearchTool(SerpApiClient(api_key="test-key")).execute(trip_type="round_trip", legs=_RT_LEGS)

    second_call_params = mock_get.call_args_list[1][1]["params"]
    assert second_call_params["departure_token"] == first_token


def test_flight_search_multi_city_makes_one_call_per_leg():
    mc_leg1 = _load("serpapi_flights_multicity.json")
    mc_leg2 = _load("serpapi_flights_multicity_leg2.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.side_effect = [_mock_response(mc_leg1), _mock_response(mc_leg2)]
        result = FlightSearchTool(SerpApiClient(api_key="test-key")).execute(trip_type="multi_city", legs=_MC_LEGS)

    assert mock_get.call_count == 2
    assert result["trip_type"] == "multi_city"
    assert len(result["legs"]) == 2
    assert result["legs"][0]["origin"] == "BOM,NMI"
    assert result["legs"][1]["origin"] == "NRT,HND"
    assert "note" in result
    for leg in result["legs"]:
        for f in leg["options"]:
            assert "departure_token" not in f
            assert "_departure_token" not in f


def test_flight_search_multi_city_leg2_uses_first_available_leg1_token():
    mc_leg1 = _load("serpapi_flights_multicity.json")
    mc_leg2 = _load("serpapi_flights_multicity_leg2.json")
    first_token = (mc_leg1["best_flights"] + mc_leg1["other_flights"])[0]["departure_token"]
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.side_effect = [_mock_response(mc_leg1), _mock_response(mc_leg2)]
        FlightSearchTool(SerpApiClient(api_key="test-key")).execute(trip_type="multi_city", legs=_MC_LEGS)

    assert mock_get.call_args_list[1][1]["params"]["departure_token"] == first_token


def test_flight_search_multi_city_uses_multi_city_json():
    mc_leg1 = _load("serpapi_flights_multicity.json")
    mc_leg2 = _load("serpapi_flights_multicity_leg2.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.side_effect = [_mock_response(mc_leg1), _mock_response(mc_leg2)]
        FlightSearchTool(SerpApiClient(api_key="test-key")).execute(trip_type="multi_city", legs=_MC_LEGS)

    params = mock_get.call_args_list[0][1]["params"]
    assert params["type"] == "3"
    legs_sent = json.loads(params["multi_city_json"])
    assert legs_sent[0]["departure_id"] == "BOM,NMI"
    assert legs_sent[0]["arrival_id"]   == "NRT,HND"
    assert legs_sent[1]["departure_id"] == "NRT,HND"
    assert legs_sent[1]["arrival_id"]   == "DEL"


def test_flight_search_multi_city_partial_when_chain_breaks():
    """When the departure_token is missing for a later leg, the tool returns status='partial'."""
    mc_leg1 = _load("serpapi_flights_multicity.json")
    # Strip departure_token from all leg1 results so the chain breaks immediately
    partial_leg1 = json.loads(json.dumps(mc_leg1))
    for f in partial_leg1.get("best_flights", []) + partial_leg1.get("other_flights", []):
        f.pop("departure_token", None)

    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(partial_leg1)
        result = FlightSearchTool(SerpApiClient(api_key="test-key")).execute(
            trip_type="multi_city", legs=_MC_LEGS
        )

    # Only one API call made (chain broke before leg 2)
    assert mock_get.call_count == 1
    assert result["status"] == "partial"
    assert result["legs_requested"] == 2
    assert result["legs_fetched"] == 1
    assert len(result["legs"]) == 1
    assert "incomplete" in result["note"].lower()


def test_flight_search_multi_city_ok_status_when_all_legs_fetched():
    mc_leg1 = _load("serpapi_flights_multicity.json")
    mc_leg2 = _load("serpapi_flights_multicity_leg2.json")
    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.side_effect = [_mock_response(mc_leg1), _mock_response(mc_leg2)]
        result = FlightSearchTool(SerpApiClient(api_key="test-key")).execute(
            trip_type="multi_city", legs=_MC_LEGS
        )

    assert result.get("status", "ok") == "ok"
    assert result.get("legs_requested") is None
    assert result.get("legs_fetched") is None


def test_flight_search_round_trip_partial_when_no_departure_token():
    """When outbound results have no departure_token, return leg is unfetchable — status='partial'."""
    rt_outbound = _load("serpapi_flights_roundtrip.json")
    no_token = json.loads(json.dumps(rt_outbound))
    for f in no_token.get("best_flights", []) + no_token.get("other_flights", []):
        f.pop("departure_token", None)

    with patch("clients.serpapi_client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(no_token)
        result = FlightSearchTool(SerpApiClient(api_key="test-key")).execute(
            trip_type="round_trip", legs=_RT_LEGS
        )

    assert mock_get.call_count == 1  # return leg never fetched
    assert result["status"] == "partial"
    assert result["legs_requested"] == 2
    assert result["legs_fetched"] == 1
    assert len(result["legs"]) == 1
    assert "departure token" in result["note"].lower()


def test_flight_search_validation_one_way_rejects_two_legs():
    result = FlightSearchTool(SerpApiClient(api_key="test-key")).execute(
        trip_type="one_way", legs=[_ONE_WAY_LEG, _ONE_WAY_LEG]
    )
    assert result["status"] == "error"
    assert "1 leg" in result["error"]


def test_flight_search_validation_round_trip_rejects_one_leg():
    result = FlightSearchTool(SerpApiClient(api_key="test-key")).execute(
        trip_type="round_trip", legs=[_ONE_WAY_LEG]
    )
    assert result["status"] == "error"
    assert "2 legs" in result["error"]


def test_flight_search_validation_round_trip_rejects_three_legs():
    result = FlightSearchTool(SerpApiClient(api_key="test-key")).execute(
        trip_type="round_trip", legs=[_ONE_WAY_LEG, _RT_LEGS[1], _MC_LEGS[1]]
    )
    assert result["status"] == "error"
    assert "2 legs" in result["error"]


def test_flight_search_validation_multi_city_rejects_one_leg():
    result = FlightSearchTool(SerpApiClient(api_key="test-key")).execute(
        trip_type="multi_city", legs=[_ONE_WAY_LEG]
    )
    assert result["status"] == "error"
    assert "2 legs" in result["error"] or "at least" in result["error"]


def test_flight_search_validation_dates_must_be_increasing():
    result = FlightSearchTool(SerpApiClient(api_key="test-key")).execute(
        trip_type="round_trip",
        legs=[
            {"origin_airports": ["BOM"], "destination_airports": ["NRT"], "date": "2026-07-20"},
            {"origin_airports": ["NRT"], "destination_airports": ["BOM"], "date": "2026-07-13"},
        ],
    )
    assert result["status"] == "error"
    assert "2026-07-13" in result["error"] or "after" in result["error"]


def test_flight_search_validation_same_date_rejected():
    result = FlightSearchTool(SerpApiClient(api_key="test-key")).execute(
        trip_type="round_trip",
        legs=[
            {"origin_airports": ["BOM"], "destination_airports": ["NRT"], "date": "2026-07-13"},
            {"origin_airports": ["NRT"], "destination_airports": ["BOM"], "date": "2026-07-13"},
        ],
    )
    assert result["status"] == "error"


def test_flight_search_validation_invalid_date_format():
    result = FlightSearchTool(SerpApiClient(api_key="test-key")).execute(
        trip_type="one_way",
        legs=[{"origin_airports": ["BOM"], "destination_airports": ["NRT"], "date": "13-07-2026"}],
    )
    assert result["status"] == "error"


def test_flight_search_429_returns_error():
    error_resp = MagicMock()
    error_resp.status_code = 429
    error_resp.json.return_value = {"error": "your account has run out of searches"}
    with patch("clients.serpapi_client.httpx.get", return_value=error_resp):
        result = FlightSearchTool(SerpApiClient(api_key="test-key")).execute(
            trip_type="one_way", legs=[{"origin_airports": ["BOM"], "destination_airports": ["NRT"], "date": "2026-07-13"}]
        )

    assert result["status"] == "error"
    assert "quota" in result["error"].lower() or "searches" in result["error"].lower()
    assert "fallback" in result


def test_flight_search_empty_results_returns_error():
    empty = {"best_flights": [], "other_flights": [], "_fixture_meta": {}}
    with patch("clients.serpapi_client.httpx.get", return_value=_mock_response(empty)):
        result = FlightSearchTool(SerpApiClient(api_key="test-key")).execute(
            trip_type="one_way", legs=[{"origin_airports": ["BOM"], "destination_airports": ["NRT"], "date": "2026-07-13"}]
        )

    assert result["status"] == "error"
    assert "no flights" in result["error"].lower()
    assert "fallback" in result


# ---------------------------------------------------------------------------
# CalculateTool
# ---------------------------------------------------------------------------

def test_calculate_basic_expression():
    tool = CalculateTool()
    result = tool.execute(expression="(850 * 4 + 120) / 4", label="per-person flight")
    assert result["result"] == 880.0   # (3400 + 120) / 4
    assert result["label"] == "per-person flight"


def test_calculate_multi_operator_with_parentheses():
    tool = CalculateTool()
    result = tool.execute(expression="(100 + 200) * 3 - 50 / 2", label="test")
    assert result["result"] == 875.0


def test_calculate_rejects_function_call():
    tool = CalculateTool()
    result = tool.execute(expression="sqrt(4)", label="bad")
    assert result["status"] == "error"


def test_calculate_rejects_attribute_access():
    tool = CalculateTool()
    result = tool.execute(expression="os.getcwd()", label="bad")
    assert result["status"] == "error"


def test_calculate_division_by_zero():
    tool = CalculateTool()
    result = tool.execute(expression="10 / 0", label="div zero")
    assert result["status"] == "error"


def test_calculate_unary_minus():
    tool = CalculateTool()
    result = tool.execute(expression="-5 * 3", label="unary")
    assert result["result"] == -15.0


# ---------------------------------------------------------------------------
# FileWriteTool
# ---------------------------------------------------------------------------

def test_file_write_creates_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tool = FileWriteTool()
    result = tool.execute(filename="itinerary_tokyo_2026-06-20_v1.md", content="# Tokyo Trip\n\nDay 1...")
    assert result["status"] == "ok"
    assert (tmp_path / "itinerary_tokyo_2026-06-20_v1.md").read_text() == "# Tokyo Trip\n\nDay 1..."
    assert result["path"] == "itinerary_tokyo_2026-06-20_v1.md"


def test_file_write_increments_version_on_collision(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tool = FileWriteTool()
    tool.execute(filename="comparison_bali_2026-09_v1.md", content="first")
    result = tool.execute(filename="comparison_bali_2026-09_v1.md", content="second")
    assert result["path"] == "comparison_bali_2026-09_v2.md"
    assert (tmp_path / "comparison_bali_2026-09_v2.md").read_text() == "second"
    assert (tmp_path / "comparison_bali_2026-09_v1.md").read_text() == "first"


def test_file_write_increments_multiple_times(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tool = FileWriteTool()
    tool.execute(filename="itinerary_v1.md", content="v1")
    tool.execute(filename="itinerary_v1.md", content="v2")
    result = tool.execute(filename="itinerary_v1.md", content="v3")
    assert result["path"] == "itinerary_v3.md"
