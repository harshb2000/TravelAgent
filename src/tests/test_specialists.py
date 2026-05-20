"""
Tests for specialist agents and their wrapper tools.
Each specialist section follows the TDD pattern from the plan.
"""
import json
import pytest
from unittest.mock import MagicMock, patch, call

from clients.llm_client import LLMClient
from tools.base import BaseTool
from models.knowledge_state import (
    DestinationCandidate,
    KnowledgeState,
    UserContext,
)


# ---------------------------------------------------------------------------
# Test helpers shared across specialists
# ---------------------------------------------------------------------------

def make_llm() -> MagicMock:
    return MagicMock(spec=LLMClient)


def stop_msg(content: str) -> dict:
    return {"role": "assistant", "content": content, "finish_reason": "stop"}


def tool_call_msg(calls: list[dict]) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "finish_reason": "tool_calls",
        "tool_calls": [
            {
                "id": c["id"],
                "type": "function",
                "function": {"name": c["name"], "arguments": json.dumps(c.get("args", {}))},
            }
            for c in calls
        ],
    }


def _candidate(name: str, turn: int = 0, query: str = "beach trip") -> DestinationCandidate:
    c = DestinationCandidate(
        name=name, country="TestCountry", vibe_tags=["beach"],
        rationale=f"Beautiful {name}", source_url="http://example.com",
        query=query,
    )
    c.added_at = turn
    return c


# ===========================================================================
# Phase 5b: ExplorerSpecialist
# ===========================================================================

from specialists.explorer import ExplorerSpecialist, EXPLORER_CACHE_THRESHOLD
from tools.explorer_wrapper import ExplorerWrapperTool


def _valid_candidate_json(name: str = "Prague", country: str = "Czech Republic") -> str:
    return json.dumps([{
        "name": name,
        "country": country,
        "vibe_tags": ["city", "culture"],
        "rationale": f"Great city trip to {name}",
        "source_url": "http://example.com",
        "query": "city trip Europe",
        # added_at intentionally omitted — system-managed field
    }])


# ---- ExplorerSpecialist.run() output structure ----

def test_explorer_run_parses_candidate_list():
    """Stub LLM returns a valid candidate JSON; run() produces DestinationCandidates with wordset."""
    llm = make_llm()
    llm.chat.return_value = stop_msg(_valid_candidate_json("Prague"))

    specialist = ExplorerSpecialist(llm, [])
    results = specialist.run("city trips Europe", max_results=1)

    assert len(results) == 1
    assert results[0].name == "Prague"
    assert results[0].country == "Czech Republic"
    assert isinstance(results[0].wordset, frozenset)
    assert len(results[0].wordset) > 0


def test_explorer_run_dispatches_web_search():
    """Stub LLM does one web_search call then returns final answer."""
    from tools.web_search import WebSearchTool

    llm = make_llm()
    search_tool = MagicMock(spec=WebSearchTool)
    search_tool.name = "web_search"
    search_tool.execute.return_value = {"results": [{"title": "Prague", "url": "http://ex.com", "content": "great", "score": 0.9}]}
    search_tool.to_llm_definition.return_value = {"type": "function", "function": {"name": "web_search", "parameters": {}}}

    llm.chat.side_effect = [
        tool_call_msg([{"id": "c1", "name": "web_search", "args": {"query": "city trips"}}]),
        stop_msg(_valid_candidate_json("Prague")),
    ]

    specialist = ExplorerSpecialist(llm, [search_tool])
    results = specialist.run("city trips Europe", max_results=1)

    search_tool.execute.assert_called_once()
    assert len(results) == 1


# ---- Wrapper pre-firing check: blocklist exclusion ----

def test_explorer_wrapper_excludes_blocklisted_candidates():
    """Candidates whose name is in blocklist are excluded before Jaccard runs."""
    llm = make_llm()
    llm.chat.return_value = stop_msg(_valid_candidate_json("Bangkok"))

    ks = KnowledgeState()
    # Add "Thailand" candidate that will be in blocklist
    thailand_candidate = _candidate("Thailand", turn=1, query="beach")
    ks.add_candidates([thailand_candidate])

    uc = UserContext("not Thailand, prefer Europe")
    specialist = ExplorerSpecialist(llm, [])
    wrapper = ExplorerWrapperTool(specialist, ks, uc)

    result = wrapper.execute(query="beach trip from Europe")

    # Thailand should not appear in summary
    summary = result.get("summary", "")
    assert "Thailand" not in summary


# ---- Wrapper pre-firing check: full cache hit, sorted by relevance ----

def test_explorer_wrapper_full_cache_hit_returns_highest_scoring():
    """When more cached candidates pass the threshold than max_results, the most relevant ones are returned."""
    llm = make_llm()
    ks = KnowledgeState()

    # High relevance: query closely matches "city culture Europe"
    high = DestinationCandidate(
        name="Prague", country="Czech Republic",
        vibe_tags=["city", "culture"],
        rationale="vibrant city culture trip in Europe",
        source_url="http://ex.com",
        query="city culture Europe",
    )
    # Low relevance: only "city" overlaps
    low = DestinationCandidate(
        name="Bangkok", country="Thailand",
        vibe_tags=["city", "budget"],
        rationale="cheap city street food",
        source_url="http://ex.com",
        query="cheap city budget Asia",
    )
    ks.add_candidates([low, high])  # low added first — insertion order would return it first without sorting

    uc = UserContext("city culture Europe")
    specialist = ExplorerSpecialist(llm, [])
    wrapper = ExplorerWrapperTool(specialist, ks, uc)

    result = wrapper.execute(query="city culture Europe", max_results=1)

    llm.chat.assert_not_called()
    assert "Prague" in result["summary"]
    assert "Bangkok" not in result["summary"]


def test_explorer_wrapper_full_cache_hit_skips_specialist():
    """K >= max_results candidates above threshold → specialist not called."""
    llm = make_llm()
    ks = KnowledgeState()
    # Add candidates with query that closely matches incoming query
    for i in range(5):
        c = DestinationCandidate(
            name=f"City{i}", country="Europe",
            vibe_tags=["city", "culture"],
            rationale="vibrant city culture trip",
            source_url="http://ex.com",
            query="city culture Europe trip",
        )
        c.added_at = i
        ks.add_candidates([c])

    uc = UserContext("city culture Europe")
    specialist = ExplorerSpecialist(llm, [])
    wrapper = ExplorerWrapperTool(specialist, ks, uc)

    result = wrapper.execute(query="city culture Europe trip", max_results=5)

    # LLM should NOT have been called (cache hit)
    llm.chat.assert_not_called()
    assert result.get("cached", False) is True or "cached" in result.get("summary", "").lower() or result.get("from_cache") is True


# ---- Wrapper pre-firing check: partial cache hit ----

def test_explorer_wrapper_partial_cache_hit_reduces_max_results():
    """K < max_results matching candidates → specialist called with max_results = max_results - K."""
    llm = make_llm()
    llm.chat.return_value = stop_msg(_valid_candidate_json("Lisbon", "Portugal"))

    ks = KnowledgeState()
    # 2 matching candidates (query closely matches)
    for name in ["Prague", "Berlin"]:
        c = DestinationCandidate(
            name=name, country="Europe",
            vibe_tags=["city", "culture"],
            rationale="vibrant city culture trip",
            source_url="http://ex.com",
            query="city culture Europe trip",
        )
        c.added_at = 1
        ks.add_candidates([c])

    uc = UserContext("city culture Europe")
    specialist = ExplorerSpecialist(llm, [])
    wrapper = ExplorerWrapperTool(specialist, ks, uc)

    # Request 5, 2 cached → specialist should run for 3 more
    result = wrapper.execute(query="city culture Europe trip", max_results=5)

    llm.chat.assert_called()
    # Specialist invocation should have used reduced max_results
    specialist_call_args = specialist._last_run_max_results  # set by specialist.run()
    assert specialist_call_args == 3


# ---- Negative constraints in task string ----

def test_explorer_wrapper_negative_constraints_in_task():
    """Blocklist terms from UserContext appear as explicit exclusions in the specialist task."""
    llm = make_llm()
    llm.chat.return_value = stop_msg(_valid_candidate_json("Prague"))

    ks = KnowledgeState()
    uc = UserContext("not Thailand, not Bali")
    specialist = ExplorerSpecialist(llm, [])
    wrapper = ExplorerWrapperTool(specialist, ks, uc)

    wrapper.execute(query="beach trip")

    # The task passed to specialist should contain the negative constraints
    assert specialist._last_run_query is not None
    assert "thailand" in specialist._last_run_query.lower() or "bali" in specialist._last_run_query.lower()


# ---- Wrapper exception handling ----

def test_explorer_wrapper_specialist_exception_returns_error_string():
    """specialist.run() raises → wrapper returns error string; knowledge not updated."""
    llm = make_llm()
    ks = KnowledgeState()
    uc = UserContext("city trip")
    specialist = ExplorerSpecialist(llm, [])
    specialist.run = MagicMock(side_effect=RuntimeError("API error"))
    wrapper = ExplorerWrapperTool(specialist, ks, uc)

    result = wrapper.execute(query="city trip Europe")

    assert "error" in result.get("summary", "").lower() or result.get("status") == "error"
    assert len(ks.candidates) == 0


# ===========================================================================
# Phase 5c: WeatherSpecialist
# ===========================================================================

from specialists.weather import WeatherSpecialist
from tools.slice_weather_range import SliceWeatherRangeTool
from tools.weather_wrapper import WeatherWrapperTool as WeatherWrapperToolCls
from tools.weather_forecast import WeatherForecastTool
from tools.climate_summary import ClimateSummaryTool
from models.weather import WeatherOutput, DailyWeather
from models.knowledge_state import DateRange


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


# ---- SliceWeatherRangeTool ----

def test_slice_tool_returns_subset_of_days():
    """slice_weather_range slices existing KnowledgeState days to the requested date range."""
    ks = KnowledgeState()
    days = [_climate_day(f"2026-06-{d:02d}") for d in range(1, 31)]
    ks.update_weather("Tokyo", DateRange.from_string("2026-06-01 to 2026-06-30"),
                      WeatherOutput(mode="climate", city="Tokyo", days=days))

    tool = SliceWeatherRangeTool(ks)
    result = tool.execute(
        destination="Tokyo",
        source_range="2026-06-01 to 2026-06-30",
        start_date="2026-06-10",
        end_date="2026-06-15",
    )

    assert result["status"] == "ok"
    assert result["mode"] == "climate"
    assert len(result["days"]) == 6
    assert result["days"][0]["date"] == "2026-06-10"
    assert result["days"][-1]["date"] == "2026-06-15"


def test_slice_tool_missing_destination_returns_error():
    ks = KnowledgeState()
    tool = SliceWeatherRangeTool(ks)
    result = tool.execute(destination="Nowhere", source_range="2026-06-01 to 2026-06-30")
    assert result["status"] == "error"


def test_slice_tool_missing_source_range_returns_error():
    ks = KnowledgeState()
    days = [_climate_day("2026-06-01")]
    ks.update_weather("Tokyo", DateRange.from_string("2026-06-01 to 2026-06-30"),
                      WeatherOutput(mode="climate", city="Tokyo", days=days))
    tool = SliceWeatherRangeTool(ks)
    result = tool.execute(destination="Tokyo", source_range="nonexistent label")
    assert result["status"] == "error"


# ---- WeatherSpecialist.run() — writes to KnowledgeState, returns None ----

def test_weather_specialist_subset_calls_slice_only():
    """LLM calls slice_weather_range alone; no forecast tool dispatched; KS updated."""
    ks = KnowledgeState()
    june_days = [_climate_day(f"2026-06-{d:02d}") for d in range(1, 31)]
    ks.update_weather("Tokyo", DateRange.from_string("2026-06-01 to 2026-06-30"),
                      WeatherOutput(mode="climate", city="Tokyo", days=june_days))

    slice_tool = SliceWeatherRangeTool(ks)
    forecast_mock = MagicMock(spec=WeatherForecastTool)
    forecast_mock.name = "weather_forecast"
    forecast_mock.to_llm_definition.return_value = {
        "type": "function", "function": {"name": "weather_forecast", "parameters": {}}}

    sliced_days = june_days[9:15]  # 10th–15th (6 days)

    llm = make_llm()
    llm.chat.return_value = tool_call_msg([{
        "id": "s1", "name": "slice_weather_range",
        "args": {"destination": "Tokyo", "source_range": "2026-06-01 to 2026-06-30",
                 "start_date": "2026-06-10", "end_date": "2026-06-15"},
    }])

    specialist = WeatherSpecialist(llm, [slice_tool, forecast_mock], ks)
    specialist.run("Tokyo", "2026-06-10 to 2026-06-15",
                   existing_entries={"2026-06-01 to 2026-06-30": "climate, 30 days"})

    forecast_mock.execute.assert_not_called()
    # Exactly 1 LLM call — no second call to synthesise JSON
    assert llm.chat.call_count == 1
    # Result written to KnowledgeState under the target DateRange key
    target_dr = DateRange.from_string("2026-06-10 to 2026-06-15")
    assert target_dr in ks.destinations["Tokyo"].weather
    assert len(ks.destinations["Tokyo"].weather[target_dr].days) == 6


def test_weather_specialist_augment_parallel_calls():
    """LLM issues slice + forecast in parallel; Python merges; exactly 1 LLM call; KS updated."""
    ks = KnowledgeState()
    existing_days = [_forecast_day(f"2026-06-{d:02d}") for d in range(20, 26)]  # 6 days
    ks.update_weather("Tokyo", DateRange.from_string("2026-06-20 to 2026-06-25"),
                      WeatherOutput(mode="forecast", city="Tokyo", days=existing_days))

    slice_tool = SliceWeatherRangeTool(ks)
    forecast_mock = MagicMock(spec=WeatherForecastTool)
    forecast_mock.name = "weather_forecast"
    forecast_mock.to_llm_definition.return_value = {
        "type": "function", "function": {"name": "weather_forecast", "parameters": {}}}
    new_days = [_forecast_day(f"2026-06-{d:02d}") for d in range(26, 31)]  # 5 days
    forecast_mock.execute.return_value = {
        "mode": "forecast", "city": "Tokyo", "days": [d.model_dump() for d in new_days]}

    llm = make_llm()
    llm.chat.return_value = tool_call_msg([
        {"id": "s1", "name": "slice_weather_range",
         "args": {"destination": "Tokyo", "source_range": "2026-06-20 to 2026-06-25"}},
        {"id": "f1", "name": "weather_forecast",
         "args": {"city": "Tokyo", "start_date": "2026-06-26", "end_date": "2026-06-30"}},
    ])

    specialist = WeatherSpecialist(llm, [slice_tool, forecast_mock], ks)
    specialist.run("Tokyo", "2026-06-20 to 2026-06-30",
                   existing_entries={"2026-06-20 to 2026-06-25": "forecast, 6 days"})

    forecast_mock.execute.assert_called_once()
    assert llm.chat.call_count == 1   # no extra LLM call — Python does the merge
    target_dr = DateRange.from_string("2026-06-20 to 2026-06-30")
    assert target_dr in ks.destinations["Tokyo"].weather
    assert len(ks.destinations["Tokyo"].weather[target_dr].days) == 11


def test_weather_specialist_no_tool_calls_raises():
    """LLM returns a text response (no tool calls) → specialist raises ValueError."""
    ks = KnowledgeState()
    llm = make_llm()
    llm.chat.return_value = stop_msg("The weather in Tokyo is nice.")
    specialist = WeatherSpecialist(llm, [], ks)
    with pytest.raises(ValueError, match="no tool calls"):
        specialist.run("Tokyo", "2026-06-20")


def test_weather_specialist_malformed_tool_result_raises():
    """Tool returns data that fails WeatherOutput validation → clear ValueError, not raw Pydantic noise."""
    ks = KnowledgeState()
    bad_tool = MagicMock(spec=WeatherForecastTool)
    bad_tool.name = "weather_forecast"
    bad_tool.to_llm_definition.return_value = {
        "type": "function", "function": {"name": "weather_forecast", "parameters": {}}}
    # Missing required fields — will fail WeatherOutput validation
    bad_tool.execute.return_value = {"mode": "forecast", "days": [{"date": "2026-06-20"}]}

    llm = make_llm()
    llm.chat.return_value = tool_call_msg([{
        "id": "f1", "name": "weather_forecast",
        "args": {"city": "Tokyo", "start_date": "2026-06-20", "end_date": "2026-06-20"},
    }])

    specialist = WeatherSpecialist(llm, [bad_tool], ks)
    with pytest.raises(ValueError, match="malformed weather data"):
        specialist.run("Tokyo", "2026-06-20")


# ---- WeatherWrapperTool ----

def test_weather_wrapper_cache_hit_skips_specialist():
    """Exact DateRange key in KnowledgeState → specialist not called."""
    llm = make_llm()
    ks = KnowledgeState()
    dr = DateRange.from_string("2026-06-20 to 2026-06-25")
    days = [_forecast_day(f"2026-06-{d:02d}") for d in range(20, 26)]
    ks.update_weather("Tokyo", dr, WeatherOutput(mode="forecast", city="Tokyo", days=days))

    specialist = WeatherSpecialist(llm, [], ks)
    wrapper = WeatherWrapperToolCls(specialist, ks)

    result = wrapper.execute(destination="Tokyo", date_range="2026-06-20 to 2026-06-25")

    llm.chat.assert_not_called()
    assert result["status"] == "ok"
    assert "Tokyo" in result["summary"]


def test_weather_wrapper_forecast_template_format():
    """Forecast mode summary includes avg high/low and precipitation probability."""
    ks = KnowledgeState()
    dr = DateRange.from_string("2026-06-20 to 2026-06-22")
    days = [
        DailyWeather(date="2026-06-20", temp_max=32.0, temp_min=24.0,
                     precipitation_prob=10, precipitation_sum=None, weather_description="Sunny"),
        DailyWeather(date="2026-06-21", temp_max=28.0, temp_min=22.0,
                     precipitation_prob=30, precipitation_sum=None, weather_description="Cloudy"),
        DailyWeather(date="2026-06-22", temp_max=30.0, temp_min=23.0,
                     precipitation_prob=20, precipitation_sum=None, weather_description="Sunny"),
    ]
    ks.update_weather("Tokyo", dr, WeatherOutput(mode="forecast", city="Tokyo", days=days))

    wrapper = WeatherWrapperToolCls(WeatherSpecialist(make_llm(), [], ks), ks)
    result = wrapper.execute(destination="Tokyo", date_range="2026-06-20 to 2026-06-22")

    summary = result["summary"]
    assert "°C" in summary
    assert "%" in summary   # precip probability


def test_weather_wrapper_climate_template_format():
    """Climate mode summary includes 'historical avg' label and precipitation sum."""
    ks = KnowledgeState()
    dr = DateRange.from_string("June 2026")
    days = [
        DailyWeather(date=f"2026-06-{d:02d}", temp_max=28.0, temp_min=20.0,
                     precipitation_prob=None, precipitation_sum=4.0, weather_description="")
        for d in range(1, 4)
    ]
    ks.update_weather("Tokyo", dr, WeatherOutput(mode="climate", city="Tokyo", days=days))

    wrapper = WeatherWrapperToolCls(WeatherSpecialist(make_llm(), [], ks), ks)
    result = wrapper.execute(destination="Tokyo", date_range="June 2026")

    summary = result["summary"]
    assert "historical" in summary.lower()
    assert "mm" in summary


def test_weather_wrapper_writes_to_ks_on_miss():
    """Cache miss → specialist called; result written to KnowledgeState by specialist."""
    ks = KnowledgeState()
    days = [_forecast_day("2026-06-20")]
    forecast_mock = MagicMock(spec=WeatherForecastTool)
    forecast_mock.name = "weather_forecast"
    forecast_mock.to_llm_definition.return_value = {
        "type": "function", "function": {"name": "weather_forecast", "parameters": {}}}
    forecast_mock.execute.return_value = {
        "mode": "forecast", "city": "Tokyo", "days": [d.model_dump() for d in days]}

    llm = make_llm()
    llm.chat.return_value = tool_call_msg([{
        "id": "f1", "name": "weather_forecast",
        "args": {"city": "Tokyo", "start_date": "2026-06-20", "end_date": "2026-06-20"},
    }])

    specialist = WeatherSpecialist(llm, [forecast_mock], ks)
    wrapper = WeatherWrapperToolCls(specialist, ks)
    result = wrapper.execute(destination="Tokyo", date_range="2026-06-20")

    assert result["status"] == "ok"
    dr = DateRange.from_string("2026-06-20")
    assert dr in ks.destinations["Tokyo"].weather


def test_weather_wrapper_specialist_exception_returns_error():
    """specialist.run() raises → wrapper returns error; KnowledgeState unchanged."""
    ks = KnowledgeState()
    specialist = WeatherSpecialist(make_llm(), [], ks)
    specialist.run = MagicMock(side_effect=RuntimeError("geocode failed"))
    wrapper = WeatherWrapperToolCls(specialist, ks)

    result = wrapper.execute(destination="Nowhereville", date_range="2026-06-20")

    assert result["status"] == "error"
    assert "Nowhereville" not in ks.destinations
