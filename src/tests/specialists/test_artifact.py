import pytest
from unittest.mock import MagicMock

from tests.helpers import make_llm, stop_msg, tool_call_msg
from models.knowledge_state import (
    KnowledgeState,
    UserContext,
    DestinationResearch,
    DestinationBudget,
    CostWithAttribution,
    StringWithAttribution,
    NotableArea,
    Activity,
    TravelOption,
    DateRange,
    DestinationCandidate,
    Itinerary,
    ItineraryDay,
    TimeSlot,
)
from models.weather import WeatherOutput, DailyWeather
from specialists.artifact import ArtifactSpecialist
from tools.artifact_wrapper import ArtifactWrapperTool
from tools.get_compiled import (
    GetResearchCompiledTool,
    GetBudgetCompiledTool,
    GetWeatherCompiledTool,
    GetRouteCompiledTool,
    GetCandidatesCompiledTool,
)
from tools.get_itinerary import GetItineraryTool
from tools.base import BaseTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_research(ks: KnowledgeState, destination: str = "Tokyo") -> None:
    ks.update_research(destination, DestinationResearch(
        name=destination,
        country="Japan",
        depth="full",
        vibe="vibrant metropolis",
        summary="Great city for culture and food.",
        top_attractions=["Senso-ji", "Shibuya Crossing"],
        safety_summary=StringWithAttribution(text="Generally safe", source_url="https://example.com/safety"),
        visa_complexity={"Indian passport": StringWithAttribution(text="e-visa $25", source_url="https://example.com/visa")},
        festivals=["Hanami", "Obon"],
        notable_areas={"Shinjuku": NotableArea(description="Bustling hub for nightlife and shopping", highlights=["Golden Gai", "Kabukicho"], source_url="https://example.com/shinjuku")},
        activities=[Activity(name="teamLab Planets", tags=["art", "indoor"], indoor=True, duration_min=90, source_url="https://example.com/teamlab")],
    ))


def _mock_tool(name: str, execute_return: dict) -> MagicMock:
    tool = MagicMock(spec=BaseTool)
    tool.name = name
    tool.to_llm_definition.return_value = {"type": "function", "function": {"name": name, "description": "", "parameters": {}}}
    tool.execute.return_value = execute_return
    return tool


# ---------------------------------------------------------------------------
# GetResearchCompiledTool
# ---------------------------------------------------------------------------

def test_get_research_compiled_returns_structured_data():
    ks = KnowledgeState()
    _seed_research(ks)
    result = GetResearchCompiledTool(ks).execute(destination="Tokyo")
    text = result["result"]
    assert "vibrant metropolis" in text
    assert "Senso-ji" in text
    assert "Great city" in text
    assert "Generally safe" in text
    assert "[source](https://example.com/safety)" in text
    assert "Indian passport" in text
    assert "[source](https://example.com/visa)" in text
    assert "Shinjuku" in text
    assert "[source](https://example.com/shinjuku)" in text
    assert "teamLab Planets" in text
    assert "[source](https://example.com/teamlab)" in text


def test_get_research_compiled_error_when_absent():
    result = GetResearchCompiledTool(KnowledgeState()).execute(destination="Paris")
    assert "Paris" in result["result"]
    assert len(result["result"]) > 10  # informative, not empty


# ---------------------------------------------------------------------------
# GetBudgetCompiledTool
# ---------------------------------------------------------------------------

def test_get_budget_compiled_returns_costs_with_source():
    ks = KnowledgeState()
    ks.update_destination_budget("Tokyo", DestinationBudget(
        accommodation={"mid-range hotel": CostWithAttribution(amount=80.0, source_url="https://example.com/hotel")},
        food={"street food": CostWithAttribution(amount=8.0, source_url=None)},
        local_transport={"metro day pass": CostWithAttribution(amount=5.0, source_url=None)},
        activities={"temple entry": CostWithAttribution(amount=5.0, source_url=None)},
    ))
    result = GetBudgetCompiledTool(ks).execute(destination="Tokyo")
    text = result["result"]
    assert "mid-range hotel" in text
    assert "$80.00" in text
    assert "[source](https://example.com/hotel)" in text
    assert "street food" in text
    assert "metro day pass" in text
    assert "temple entry" in text


def test_get_budget_compiled_error_when_absent():
    result = GetBudgetCompiledTool(KnowledgeState()).execute(destination="Tokyo")
    assert "Tokyo" in result["result"]
    assert len(result["result"]) > 10


# ---------------------------------------------------------------------------
# GetWeatherCompiledTool
# ---------------------------------------------------------------------------

def test_get_weather_compiled_returns_days():
    ks = KnowledgeState()
    dr = DateRange.from_string("June 2026")
    wo = WeatherOutput(
        mode="climate",
        city="Tokyo",
        days=[DailyWeather(date="2026-06-01", temp_max=28.0, temp_min=20.0, precipitation_prob=None, precipitation_sum=5.0, weather_description="")],
    )
    ks.update_weather("Tokyo", dr, wo)
    result = GetWeatherCompiledTool(ks).execute(destination="Tokyo", date_range="June 2026")
    text = result["result"]
    assert "Tokyo" in text
    assert "2026-06-01" in text
    assert "20" in text
    assert "28" in text


def test_get_weather_compiled_error_when_absent():
    result = GetWeatherCompiledTool(KnowledgeState()).execute(destination="Tokyo")
    assert "Tokyo" in result["result"]
    assert len(result["result"]) > 10


# ---------------------------------------------------------------------------
# GetRouteCompiledTool
# ---------------------------------------------------------------------------

def test_get_route_compiled_returns_travel_options():
    ks = KnowledgeState()
    dr = DateRange.from_string("Jul 2026")
    ks.update_route("Mumbai", "Tokyo", dr, [
        TravelOption(mode="flight/one-way", origin="Mumbai", destination="Tokyo", cost_usd=450.0, duration_min=540),
    ])
    result = GetRouteCompiledTool(ks).execute(origin="Mumbai", destination="Tokyo", date_range="Jul 2026")
    text = result["result"]
    assert "Mumbai" in text
    assert "Tokyo" in text
    assert "flight/one-way" in text
    assert "$450" in text


def test_get_route_compiled_error_when_absent():
    result = GetRouteCompiledTool(KnowledgeState()).execute(origin="Mumbai", destination="Tokyo")
    assert "Mumbai" in result["result"] or "Tokyo" in result["result"]
    assert len(result["result"]) > 10


# ---------------------------------------------------------------------------
# GetCandidatesCompiledTool
# ---------------------------------------------------------------------------

def test_get_candidates_compiled_returns_all_candidates():
    ks = KnowledgeState()
    ks.add_candidates([
        DestinationCandidate(name="Tokyo", country="Japan", vibe_tags=["city", "cultural"], rationale="Great food scene", source_url="https://example.com/tokyo", query="city trip"),
        DestinationCandidate(name="Bali", country="Indonesia", vibe_tags=["beach", "spiritual"], rationale="Affordable paradise", source_url="https://example.com/bali", query="beach trip"),
    ])
    result = GetCandidatesCompiledTool(ks).execute()
    text = result["result"]
    assert "Tokyo" in text
    assert "Bali" in text
    assert "Great food scene" in text
    assert "[source](https://example.com/tokyo)" in text
    assert "[source](https://example.com/bali)" in text


# ---------------------------------------------------------------------------
# GetItineraryTool
# ---------------------------------------------------------------------------

def test_get_itinerary_returns_day_by_day_with_alternatives():
    ks = KnowledgeState()
    itinerary = Itinerary(
        destinations=["Tokyo"],
        start_date="2026-06-20",
        days=[
            ItineraryDay(
                day_num=1,
                location="Tokyo",
                is_arrival=True,
                slots=[
                    TimeSlot(start_time="14:00", activity=Activity(name="Senso-ji Temple", tags=["cultural"], indoor=False), is_alternative=False),
                    TimeSlot(start_time="14:00", activity=Activity(name="Tokyo National Museum", tags=["cultural"], indoor=True), is_alternative=True),
                ],
            ),
        ],
    )
    ks.update_itinerary(frozenset(["Tokyo"]), itinerary)
    result = GetItineraryTool(ks).execute(destinations=["Tokyo"])
    text = result["result"]
    assert "Day 1" in text
    assert "Senso-ji Temple" in text
    assert "Tokyo National Museum" in text
    assert "[alt]" in text


def test_get_itinerary_error_when_absent():
    result = GetItineraryTool(KnowledgeState()).execute(destinations=["Tokyo"])
    assert "Tokyo" in result["result"]
    assert len(result["result"]) > 10


# ---------------------------------------------------------------------------
# ArtifactWrapperTool
# ---------------------------------------------------------------------------

def test_artifact_wrapper_injects_context_no_ks_write():
    ks = KnowledgeState()
    _seed_research(ks)

    llm = make_llm()
    llm.chat.return_value = stop_msg('{"file_path": "/tmp/tokyo_v1.md"}')
    specialist = ArtifactSpecialist(llm, [])
    wrapper = ArtifactWrapperTool(specialist, ks, UserContext())

    n_routes = len(ks.routes)
    n_candidates = len(ks.candidates)
    n_itineraries = len(ks.itineraries)
    n_destinations = len(ks.destinations)

    result = wrapper.execute(query="Save a Tokyo travel guide")

    assert result["status"] == "ok"
    assert specialist._last_run_context is not None
    assert "DESTINATIONS" in specialist._last_run_context
    assert "Tokyo" in specialist._last_run_context

    assert len(ks.routes) == n_routes
    assert len(ks.candidates) == n_candidates
    assert len(ks.itineraries) == n_itineraries
    assert len(ks.destinations) == n_destinations


def test_artifact_wrapper_exception_returns_error():
    ks = KnowledgeState()
    llm = make_llm()
    specialist = ArtifactSpecialist(llm, [])
    specialist.run = MagicMock(side_effect=RuntimeError("LLM unavailable"))
    wrapper = ArtifactWrapperTool(specialist, ks, UserContext())
    result = wrapper.execute(query="Tokyo guide")
    assert result["status"] == "error"


