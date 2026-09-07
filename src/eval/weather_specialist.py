#!/usr/bin/env python3
"""
Assertion-based evaluation for WeatherSpecialist.

Tests A1–A8: mode selection (forecast vs climate, including vague date strings)
Tests B1–B4: slice/augment decisions given pre-seeded KnowledgeState

Every test makes one real LLM call and real weather API calls.

Usage (from src/):
    python eval/weather_specialist.py

Results saved to:
    src/eval/results/weather_specialist_<timestamp>.json
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from clients.llm_client import LLMClient
from clients.weather_client import WeatherClient
from config.settings import settings
from config.specialist_tuning import resolve_model_config
from models.knowledge_state import KnowledgeState, DateRange
from models.weather import DailyWeather, WeatherOutput
from specialists.weather import WeatherSpecialist
from tools.climate_summary import ClimateSummaryTool
from tools.slice_weather_range import SliceWeatherRangeTool
from tools.weather_forecast import WeatherForecastTool


# ---------------------------------------------------------------------------
# Capturing wrapper
# ---------------------------------------------------------------------------

class _CapturingLLM:
    """
    Wraps a real LLMClient and records tool_calls from the response.
    WeatherSpecialist makes exactly one LLM call, so last_tool_calls
    always reflects that single decision. Create a new instance per test.
    """
    def __init__(self, real: LLMClient):
        self._real = real
        self.model = real.model
        self.last_tool_calls: list[dict] = []

    def chat(self, messages, tools=None, extra_body=None, timeout=None, retries=None):
        resp = self._real.chat(
            messages, tools=tools, extra_body=extra_body, timeout=timeout, retries=retries
        )
        self.last_tool_calls = resp.get("tool_calls") or []
        return resp


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


def _make_specialist(ks: KnowledgeState, capture: _CapturingLLM) -> WeatherSpecialist:
    wc = WeatherClient()
    return WeatherSpecialist(
        capture,
        [WeatherForecastTool(wc), ClimateSummaryTool(wc), SliceWeatherRangeTool(ks)],
        ks,
    )


def _tool_names(tool_calls: list[dict]) -> list[str]:
    return [tc["function"]["name"] for tc in tool_calls]


def _calls_for(tool_calls: list[dict], name: str) -> list[dict]:
    return [tc for tc in tool_calls if tc["function"]["name"] == name]


def _build_existing_entries(ks: KnowledgeState, destination: str) -> dict[str, str]:
    """Mirror WeatherWrapperTool's existing_entries construction."""
    dk = ks.destinations.get(destination)
    if not dk:
        return {}
    result = {}
    for dr, wo in dk.weather.items():
        if wo.days:
            coverage = f"{wo.days[0].date} to {wo.days[-1].date}"
            result[dr.label] = f"{wo.mode}, {len(wo.days)} days, covers {coverage}"
        else:
            result[dr.label] = f"{wo.mode}, 0 days"
    return result


def _forecast_days(start: date, n: int) -> list[DailyWeather]:
    return [
        DailyWeather(
            date=(start + timedelta(days=i)).isoformat(),
            temp_max=25.0, temp_min=15.0,
            precipitation_prob=10, precipitation_sum=None,
            weather_description="Sunny",
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def _serialize_tool_calls(tool_calls: list[dict]) -> list[dict]:
    return [
        {
            "name": tc["function"]["name"],
            "args": json.loads(tc["function"].get("arguments", "{}")),
        }
        for tc in tool_calls
    ]


def run_test(fn, real_llm) -> dict:
    name = fn.__name__
    capture = _CapturingLLM(real_llm)
    try:
        fn(real_llm, capture)
        return {
            "name": name,
            "passed": True,
            "details": "",
            "tool_calls": _serialize_tool_calls(capture.last_tool_calls),
        }
    except AssertionError as e:
        return {
            "name": name,
            "passed": False,
            "details": str(e),
            "tool_calls": _serialize_tool_calls(capture.last_tool_calls),
        }
    except Exception as e:
        return {
            "name": name,
            "passed": False,
            "details": f"EXCEPTION: {type(e).__name__}: {e}",
            "tool_calls": _serialize_tool_calls(capture.last_tool_calls),
        }


# ---------------------------------------------------------------------------
# Group A — Mode selection
# ---------------------------------------------------------------------------

def near_term_dates_use_forecast(real_llm, capture):
    """Forecast for near-term dates (today+3 to today+10)."""
    today = date.today()
    dr = f"{(today + timedelta(3)).isoformat()} to {(today + timedelta(10)).isoformat()}"
    ks = KnowledgeState()
    _make_specialist(ks, capture).run("London", dr)
    names = _tool_names(capture.last_tool_calls)
    assert "weather_forecast" in names, f"expected weather_forecast, got {names}"
    assert "climate_summary" not in names, f"climate_summary must not be called, got {names}"


def far_term_dates_use_climate(real_llm, capture):
    """Climate for far-term dates (today+25 to today+32)."""
    today = date.today()
    dr = f"{(today + timedelta(25)).isoformat()} to {(today + timedelta(32)).isoformat()}"
    ks = KnowledgeState()
    _make_specialist(ks, capture).run("Tokyo", dr)
    names = _tool_names(capture.last_tool_calls)
    assert "climate_summary" in names, f"expected climate_summary, got {names}"
    assert "weather_forecast" not in names, f"weather_forecast must not be called, got {names}"


def vague_date_string_uses_climate(real_llm, capture):
    """Climate for vague dates ('late June'). Vague strings always use climate mode."""
    ks = KnowledgeState()
    _make_specialist(ks, capture).run("Paris", "late June")
    names = _tool_names(capture.last_tool_calls)
    assert "climate_summary" in names, f"expected climate_summary, got {names}"
    assert "weather_forecast" not in names, f"weather_forecast must not be called, got {names}"


def boundary_straddling_range_uses_climate(real_llm, capture):
    """Climate for range straddling the 16-day boundary (today+14 to today+18).

    The full range does not fit within 16 days, so climate must be used.
    Failure mode: LLM checks only the start date and calls weather_forecast.
    """
    today = date.today()
    dr = f"{(today + timedelta(14)).isoformat()} to {(today + timedelta(18)).isoformat()}"
    ks = KnowledgeState()
    _make_specialist(ks, capture).run("Mumbai", dr)
    names = _tool_names(capture.last_tool_calls)
    assert "climate_summary" in names, f"expected climate_summary for boundary range, got {names}"
    assert "weather_forecast" not in names, f"weather_forecast must not be called, got {names}"


def next_week_resolves_to_forecast(real_llm, capture):
    """'next week' resolves to a near-term forecast window (~7 days)."""
    today = date.today()
    ks = KnowledgeState()
    _make_specialist(ks, capture).run("London", "next week")
    names = _tool_names(capture.last_tool_calls)
    assert "weather_forecast" in names, f"expected weather_forecast, got {names}"
    assert "climate_summary" not in names, f"climate_summary must not be called, got {names}"

    fc = _calls_for(capture.last_tool_calls, "weather_forecast")
    args = json.loads(fc[0]["function"]["arguments"])
    start = date.fromisoformat(args["start_date"])
    end = date.fromisoformat(args["end_date"])
    span = (end - start).days + 1
    assert 5 <= span <= 9, f"expected ~7-day span for 'next week', got {span} days"
    assert start <= today + timedelta(days=7), \
        f"start_date {start} is more than 7 days from today {today}"


def next_month_resolves_to_correct_calendar_month(real_llm, capture):
    """'next month' maps to the correct calendar month and uses climate mode."""
    today = date.today()
    expected_month = today.month % 12 + 1  # Dec(12) → Jan(1), otherwise +1
    ks = KnowledgeState()
    _make_specialist(ks, capture).run("Tokyo", "next month")
    names = _tool_names(capture.last_tool_calls)
    assert "climate_summary" in names, f"expected climate_summary, got {names}"

    cc = _calls_for(capture.last_tool_calls, "climate_summary")
    args = json.loads(cc[0]["function"]["arguments"])
    start = date.fromisoformat(args["start_date"])
    assert start.month == expected_month, \
        f"expected start_date in month {expected_month}, got {args['start_date']}"


def named_month_targets_next_future_occurrence(real_llm, capture):
    """'early July' targets the next future occurrence of July, climate mode."""
    today = date.today()
    expected_year = today.year if today.month <= 7 else today.year + 1
    ks = KnowledgeState()
    _make_specialist(ks, capture).run("Paris", "early July")
    names = _tool_names(capture.last_tool_calls)
    assert "climate_summary" in names, f"expected climate_summary, got {names}"

    cc = _calls_for(capture.last_tool_calls, "climate_summary")
    args = json.loads(cc[0]["function"]["arguments"])
    start = date.fromisoformat(args["start_date"])
    assert start.month == 7, f"expected start_date in July, got {args['start_date']}"
    assert start.year == expected_year, \
        f"expected year {expected_year}, got {start.year}"


def season_name_maps_to_correct_months(real_llm, capture):
    """'winter' maps to winter months (Dec/Jan/Feb), climate mode.

    The LLM may issue one call per month or a single representative call —
    either is acceptable as long as at least one start_date falls in a winter month.
    """
    ks = KnowledgeState()
    _make_specialist(ks, capture).run("London", "winter")
    names = _tool_names(capture.last_tool_calls)
    assert "climate_summary" in names, f"expected climate_summary, got {names}"
    assert "weather_forecast" not in names, f"weather_forecast must not be called, got {names}"

    cc = _calls_for(capture.last_tool_calls, "climate_summary")
    winter = {12, 1, 2}
    start_months = [
        date.fromisoformat(json.loads(tc["function"]["arguments"])["start_date"]).month
        for tc in cc
    ]
    assert any(m in winter for m in start_months), \
        f"expected at least one winter month (Dec/Jan/Feb), got start months={start_months}"


# ---------------------------------------------------------------------------
# Group B — Slice / augment decisions
# ---------------------------------------------------------------------------

def subset_of_existing_range_slices_only(real_llm, capture):
    """Subset of existing range: only slice_weather_range should be called.

    KnowledgeState has Paris Jun 20–30. Request is Jun 22–25 (fully contained).
    """
    today = date.today()
    seed_start = today + timedelta(days=3)
    ks = KnowledgeState()
    days = _forecast_days(seed_start, 11)
    ks.update_weather(
        "Paris",
        DateRange.from_string(f"{seed_start.isoformat()} to {(seed_start + timedelta(days=10)).isoformat()}"),
        WeatherOutput(mode="forecast", city="Paris", days=days),
    )
    existing = _build_existing_entries(ks, "Paris")
    request_start = today + timedelta(days=5)
    request_end = today + timedelta(days=8)
    _make_specialist(ks, capture).run(
        "Paris", f"{request_start.isoformat()} to {request_end.isoformat()}", existing_entries=existing
    )
    names = _tool_names(capture.last_tool_calls)
    assert "slice_weather_range" in names, f"expected slice_weather_range, got {names}"
    assert "weather_forecast" not in names, f"weather_forecast must not be called, got {names}"
    assert "climate_summary" not in names, f"climate_summary must not be called, got {names}"


def same_mode_extension_slices_and_fetches_gap(real_llm, capture):
    """Same-mode extension: slice + fresh forecast must both be called in parallel.

    Existing: London forecast today+3 to today+8.
    Request: today+3 to today+12 (4-day extension, still within 16 days).
    Both tools must appear in the single LLM response (= parallel by definition).
    The fresh forecast must not restart from the beginning of the full range.
    """
    today = date.today()
    start = today + timedelta(days=3)
    end = today + timedelta(days=8)
    ks = KnowledgeState()
    source_range = f"{start.isoformat()} to {end.isoformat()}"
    ks.update_weather(
        "London",
        DateRange.from_string(source_range),
        WeatherOutput(mode="forecast", city="London", days=_forecast_days(start, 6)),
    )
    existing = _build_existing_entries(ks, "London")

    new_end = today + timedelta(days=12)
    request_range = f"{start.isoformat()} to {new_end.isoformat()}"
    _make_specialist(ks, capture).run("London", request_range, existing_entries=existing)
    names = _tool_names(capture.last_tool_calls)

    assert "slice_weather_range" in names, f"expected slice_weather_range, got {names}"
    assert "weather_forecast" in names, f"expected weather_forecast for extension, got {names}"

    fc_args = json.loads(_calls_for(capture.last_tool_calls, "weather_forecast")[0]["function"]["arguments"])
    fresh_start = date.fromisoformat(fc_args["start_date"])
    assert fresh_start > start, \
        f"fresh fetch start ({fresh_start}) should be after existing range start ({start}); " \
        f"LLM fetched the whole range from scratch instead of just the gap"


def no_existing_entry_fetches_directly(real_llm, capture):
    """No existing entry: direct fetch (forecast or climate), no slice."""
    today = date.today()
    dr = f"{(today + timedelta(days=30)).isoformat()} to {(today + timedelta(days=35)).isoformat()}"
    ks = KnowledgeState()  # empty — no weather data for Dubai
    _make_specialist(ks, capture).run("Dubai", dr)
    names = _tool_names(capture.last_tool_calls)
    assert "slice_weather_range" not in names, \
        f"slice_weather_range must not be called when no entry exists, got {names}"
    assert "weather_forecast" in names or "climate_summary" in names, \
        f"expected a direct fetch, got {names}"


def cross_mode_extension_discards_existing_and_fetches_climate(real_llm, capture):
    """Cross-mode extension: existing forecast cannot be reused when the full
    requested range exceeds 16 days. Must call climate_summary; must not slice.

    Failure mode: LLM slices the existing forecast and fetches climate for the
    tail, producing a mixed-mode WeatherOutput.
    """
    today = date.today()
    start = today + timedelta(days=3)
    end = today + timedelta(days=10)
    ks = KnowledgeState()
    source_range = f"{start.isoformat()} to {end.isoformat()}"
    ks.update_weather(
        "London",
        DateRange.from_string(source_range),
        WeatherOutput(mode="forecast", city="London", days=_forecast_days(start, 8)),
    )
    existing = _build_existing_entries(ks, "London")

    new_end = today + timedelta(days=25)
    request_range = f"{start.isoformat()} to {new_end.isoformat()}"
    _make_specialist(ks, capture).run("London", request_range, existing_entries=existing)
    names = _tool_names(capture.last_tool_calls)
    assert "climate_summary" in names, \
        f"expected climate_summary for cross-mode range, got {names}"
    assert "slice_weather_range" not in names, \
        f"slice_weather_range must not be called (forecast cannot mix with climate), got {names}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import datetime as dt

    real_llm = _make_llm()

    all_tests = [
        near_term_dates_use_forecast,
        far_term_dates_use_climate,
        vague_date_string_uses_climate,
        boundary_straddling_range_uses_climate,
        next_week_resolves_to_forecast,
        next_month_resolves_to_correct_calendar_month,
        named_month_targets_next_future_occurrence,
        season_name_maps_to_correct_months,
        subset_of_existing_range_slices_only,
        same_mode_extension_slices_and_fetches_gap,
        no_existing_entry_fetches_directly,
        cross_mode_extension_discards_existing_and_fetches_climate,
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
        result = run_test(fn, real_llm)
        results.append(result)
        print("PASS" if result["passed"] else f"FAIL  {result['details']}")

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n{passed}/{total} passed")

    output = {
        "specialist": "WeatherSpecialist",
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model": settings.llm_model,
        "results": results,
        "summary": {"passed": passed, "failed": total - passed, "total": total},
    }

    results_dir = Path(__file__).parent / "results" / "weather_specialist"
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = results_dir / f"{ts}.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
