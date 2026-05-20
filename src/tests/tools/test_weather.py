from unittest.mock import patch

from clients.weather_client import WeatherClient
from tools.weather_forecast import WeatherForecastTool
from tools.climate_summary import ClimateSummaryTool
from tools.slice_weather_range import SliceWeatherRangeTool
from models.knowledge_state import KnowledgeState, DateRange
from models.weather import WeatherOutput, DailyWeather
from tests.tools.helpers import load_fixture, mock_response, GEO_TOKYO, GEO_EMPTY


# ---------------------------------------------------------------------------
# WeatherForecastTool
# ---------------------------------------------------------------------------

def test_forecast_tool_returns_per_day_temps_and_descriptions():
    fixture = load_fixture("openmeteo_forecast_tokyo.json")
    with patch("clients.weather_client.httpx.get") as mock_get:
        mock_get.side_effect = [mock_response(GEO_TOKYO), mock_response(fixture)]
        result = WeatherForecastTool(WeatherClient()).execute(
            city="Tokyo", start_date="2026-05-14", end_date="2026-05-20")

    assert result["mode"] == "forecast"
    assert result["city"] == "Tokyo"
    days = result["days"]
    assert len(days) == 7
    day0 = days[0]
    assert day0["date"] == fixture["daily"]["time"][0]
    assert day0["temp_max"] == fixture["daily"]["temperature_2m_max"][0]
    assert day0["temp_min"] == fixture["daily"]["temperature_2m_min"][0]
    assert day0["precipitation_prob"] == fixture["daily"]["precipitation_probability_max"][0]
    assert day0["precipitation_sum"] is None
    assert "drizzle" in day0["weather_description"].lower()


def test_forecast_tool_geocoding_failure_returns_error():
    with patch("clients.weather_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(GEO_EMPTY)
        result = WeatherForecastTool(WeatherClient()).execute(
            city="Nowhere", start_date="2026-06-01", end_date="2026-06-07")
    assert result["status"] == "error"
    assert "geocod" in result["error"].lower() or "not found" in result["error"].lower()


def test_forecast_tool_geocode_cached_on_second_call():
    fixture = load_fixture("openmeteo_forecast_tokyo.json")
    with patch("clients.weather_client.httpx.get") as mock_get:
        mock_get.side_effect = [
            mock_response(GEO_TOKYO), mock_response(fixture),
            mock_response(fixture),  # second execute: only forecast, no second geo
        ]
        client = WeatherClient()
        tool = WeatherForecastTool(client)
        tool.execute(city="Tokyo", start_date="2026-05-14", end_date="2026-05-20")
        tool.execute(city="Tokyo", start_date="2026-05-21", end_date="2026-05-27")
    assert mock_get.call_count == 3


# ---------------------------------------------------------------------------
# ClimateSummaryTool
# ---------------------------------------------------------------------------

def test_climate_tool_returns_mode_city_and_days():
    fixture = load_fixture("openmeteo_climate_tokyo_june.json")
    with patch("clients.weather_client.httpx.get") as mock_get:
        mock_get.side_effect = [mock_response(GEO_TOKYO), mock_response(fixture)]
        result = ClimateSummaryTool(WeatherClient()).execute(city="Tokyo", month="June", year=2026)
    assert result["mode"] == "climate"
    assert result["city"] == "Tokyo"
    assert "note" not in result
    assert "month" not in result
    assert len(result["days"]) == 30


def test_climate_tool_day_shape():
    fixture = load_fixture("openmeteo_climate_tokyo_june.json")
    with patch("clients.weather_client.httpx.get") as mock_get:
        mock_get.side_effect = [mock_response(GEO_TOKYO), mock_response(fixture)]
        result = ClimateSummaryTool(WeatherClient()).execute(city="Tokyo", month="June", year=2026)
    day0 = result["days"][0]
    assert day0["date"] == fixture["daily"]["time"][0]
    assert day0["temp_max"] == fixture["daily"]["temperature_2m_max"][0]
    assert day0["temp_min"] == fixture["daily"]["temperature_2m_min"][0]
    assert day0["precipitation_prob"] is None
    assert day0["precipitation_sum"] == fixture["daily"]["precipitation_sum"][0]
    assert day0["weather_description"] == ""


def test_weather_and_climate_tools_share_output_schema():
    import re
    def extract_schema(desc):
        m = re.search(r"Success output schema: (.+)\nOn error:", desc, re.DOTALL)
        return m.group(1) if m else ""
    forecast_desc = WeatherForecastTool(WeatherClient()).to_llm_definition()["function"]["description"]
    climate_desc = ClimateSummaryTool(WeatherClient()).to_llm_definition()["function"]["description"]
    assert extract_schema(forecast_desc) == extract_schema(climate_desc)


def test_climate_tool_geocoding_failure_returns_error():
    with patch("clients.weather_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(GEO_EMPTY)
        result = ClimateSummaryTool(WeatherClient()).execute(city="Nowhere", month="June")
    assert result["status"] == "error"


def test_climate_tool_accepts_month_as_number():
    fixture = load_fixture("openmeteo_climate_tokyo_june.json")
    with patch("clients.weather_client.httpx.get") as mock_get:
        mock_get.side_effect = [mock_response(GEO_TOKYO), mock_response(fixture)]
        result = ClimateSummaryTool(WeatherClient()).execute(city="Tokyo", month="6", year=2026)
    assert result["mode"] == "climate"
    assert len(result["days"]) == 30


# ---------------------------------------------------------------------------
# SliceWeatherRangeTool
# ---------------------------------------------------------------------------

def _climate_day(date: str) -> DailyWeather:
    return DailyWeather(
        date=date, temp_max=28.0, temp_min=20.0,
        precipitation_prob=None, precipitation_sum=3.5, weather_description="",
    )


def test_slice_tool_returns_subset_of_days():
    ks = KnowledgeState()
    days = [_climate_day(f"2026-06-{d:02d}") for d in range(1, 31)]
    ks.update_weather("Tokyo", DateRange.from_string("2026-06-01 to 2026-06-30"),
                      WeatherOutput(mode="climate", city="Tokyo", days=days))
    result = SliceWeatherRangeTool(ks).execute(
        destination="Tokyo", source_range="2026-06-01 to 2026-06-30",
        start_date="2026-06-10", end_date="2026-06-15",
    )
    assert result["status"] == "ok"
    assert result["mode"] == "climate"
    assert len(result["days"]) == 6
    assert result["days"][0]["date"] == "2026-06-10"
    assert result["days"][-1]["date"] == "2026-06-15"


def test_slice_tool_missing_destination_returns_error():
    result = SliceWeatherRangeTool(KnowledgeState()).execute(
        destination="Nowhere", source_range="2026-06-01 to 2026-06-30")
    assert result["status"] == "error"


def test_slice_tool_missing_source_range_returns_error():
    ks = KnowledgeState()
    ks.update_weather("Tokyo", DateRange.from_string("2026-06-01 to 2026-06-30"),
                      WeatherOutput(mode="climate", city="Tokyo", days=[_climate_day("2026-06-01")]))
    result = SliceWeatherRangeTool(ks).execute(destination="Tokyo", source_range="nonexistent")
    assert result["status"] == "error"
