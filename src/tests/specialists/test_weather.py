import pytest
from unittest.mock import MagicMock

from tests.helpers import make_llm, stop_msg, tool_call_msg
from models.knowledge_state import KnowledgeState, DateRange
from models.weather import WeatherOutput, DailyWeather
from specialists.weather import WeatherSpecialist
from tools.slice_weather_range import SliceWeatherRangeTool
from tools.weather_forecast import WeatherForecastTool
from tools.weather_wrapper import WeatherWrapperTool


def _forecast_day(date: str, temp_max: float = 30.0, temp_min: float = 22.0) -> DailyWeather:
    return DailyWeather(
        date=date, temp_max=temp_max, temp_min=temp_min,
        precipitation_prob=20, precipitation_sum=None, weather_description="Sunny",
    )


def _climate_day(date: str, temp_max: float = 28.0, temp_min: float = 20.0) -> DailyWeather:
    return DailyWeather(
        date=date, temp_max=temp_max, temp_min=temp_min,
        precipitation_prob=None, precipitation_sum=3.5, weather_description="",
    )


# ---- WeatherSpecialist ----

def test_weather_specialist_merges_multiple_tool_results_into_ks():
    """When LLM issues parallel slice + forecast, Python merges and sorts the days; exactly 1 LLM call."""
    ks = KnowledgeState()
    existing_days = [_forecast_day(f"2026-06-{d:02d}") for d in range(20, 26)]  # June 20–25
    ks.update_weather("Tokyo", DateRange.from_string("2026-06-20 to 2026-06-25"),
                      WeatherOutput(mode="forecast", city="Tokyo", days=existing_days))

    slice_tool = SliceWeatherRangeTool(ks)
    forecast_mock = MagicMock(spec=WeatherForecastTool)
    forecast_mock.name = "weather_forecast"
    forecast_mock.to_llm_definition.return_value = {"type": "function", "function": {"name": "weather_forecast", "parameters": {}}}
    new_days = [_forecast_day(f"2026-06-{d:02d}") for d in range(26, 31)]  # June 26–30
    forecast_mock.execute.return_value = {
        "mode": "forecast", "city": "Tokyo", "days": [d.model_dump() for d in new_days]}

    llm = make_llm()
    llm.chat.return_value = tool_call_msg([
        {"id": "s1", "name": "slice_weather_range",
         "args": {"destination": "Tokyo", "source_range": "2026-06-20 to 2026-06-25"}},
        {"id": "f1", "name": "weather_forecast",
         "args": {"city": "Tokyo", "start_date": "2026-06-26", "end_date": "2026-06-30"}},
    ])

    WeatherSpecialist(llm, [slice_tool, forecast_mock], ks).run("Tokyo", "2026-06-20 to 2026-06-30")

    # Single LLM call — no second call to synthesise
    assert llm.chat.call_count == 1
    # Combined 11 days written to KS under the target key, sorted by date
    target_dr = DateRange.from_string("2026-06-20 to 2026-06-30")
    stored = ks.destinations["Tokyo"].weather[target_dr]
    assert len(stored.days) == 11
    assert stored.days[0].date == "2026-06-20"
    assert stored.days[-1].date == "2026-06-30"


def test_weather_specialist_no_tool_calls_raises():
    ks = KnowledgeState()
    llm = make_llm()
    llm.chat.return_value = stop_msg("The weather in Tokyo is nice.")
    with pytest.raises(ValueError, match="no tool calls"):
        WeatherSpecialist(llm, [], ks).run("Tokyo", "2026-06-20")


def test_weather_specialist_malformed_tool_result_raises():
    ks = KnowledgeState()
    bad_tool = MagicMock(spec=WeatherForecastTool)
    bad_tool.name = "weather_forecast"
    bad_tool.to_llm_definition.return_value = {"type": "function", "function": {"name": "weather_forecast", "parameters": {}}}
    bad_tool.execute.return_value = {"mode": "forecast", "days": [{"date": "2026-06-20"}]}
    llm = make_llm()
    llm.chat.return_value = tool_call_msg([{
        "id": "f1", "name": "weather_forecast",
        "args": {"city": "Tokyo", "start_date": "2026-06-20", "end_date": "2026-06-20"},
    }])
    with pytest.raises(ValueError, match="malformed weather data"):
        WeatherSpecialist(llm, [bad_tool], ks).run("Tokyo", "2026-06-20")


# ---- WeatherWrapperTool ----

def test_weather_wrapper_cache_hit_skips_specialist():
    llm = make_llm()
    ks = KnowledgeState()
    dr = DateRange.from_string("2026-06-20 to 2026-06-25")
    days = [_forecast_day(f"2026-06-{d:02d}") for d in range(20, 26)]
    ks.update_weather("Tokyo", dr, WeatherOutput(mode="forecast", city="Tokyo", days=days))
    result = WeatherWrapperTool(WeatherSpecialist(llm, [], ks), ks).execute(
        destination="Tokyo", date_range="2026-06-20 to 2026-06-25")
    llm.chat.assert_not_called()
    assert result["status"] == "ok"
    assert "Tokyo" in result["summary"]



def test_weather_wrapper_writes_to_ks_on_miss():
    ks = KnowledgeState()
    days = [_forecast_day("2026-06-20")]
    forecast_mock = MagicMock(spec=WeatherForecastTool)
    forecast_mock.name = "weather_forecast"
    forecast_mock.to_llm_definition.return_value = {"type": "function", "function": {"name": "weather_forecast", "parameters": {}}}
    forecast_mock.execute.return_value = {"mode": "forecast", "city": "Tokyo", "days": [d.model_dump() for d in days]}
    llm = make_llm()
    llm.chat.return_value = tool_call_msg([{
        "id": "f1", "name": "weather_forecast",
        "args": {"city": "Tokyo", "start_date": "2026-06-20", "end_date": "2026-06-20"},
    }])
    result = WeatherWrapperTool(WeatherSpecialist(llm, [forecast_mock], ks), ks).execute(
        destination="Tokyo", date_range="2026-06-20")
    assert result["status"] == "ok"
    assert DateRange.from_string("2026-06-20") in ks.destinations["Tokyo"].weather


def test_weather_wrapper_specialist_exception_returns_error():
    ks = KnowledgeState()
    specialist = WeatherSpecialist(make_llm(), [], ks)
    specialist.run = MagicMock(side_effect=RuntimeError("geocode failed"))
    result = WeatherWrapperTool(specialist, ks).execute(destination="Nowhereville", date_range="2026-06-20")
    assert result["status"] == "error"
    assert "Nowhereville" not in ks.destinations
