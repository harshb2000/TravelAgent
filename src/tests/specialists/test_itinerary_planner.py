import json
import pytest
from unittest.mock import MagicMock

from tests.helpers import make_llm, stop_msg
from models.knowledge_state import (
    DestinationResearch,
    KnowledgeState,
    UserContext,
)
from specialists.itinerary_planner import ItineraryPlannerSpecialist
from tools.itinerary_planner_wrapper import ItineraryPlannerWrapperTool


# ---------------------------------------------------------------------------
# JSON builders
# ---------------------------------------------------------------------------

def _activity_dict(name="Senso-ji Temple", tags=None, indoor=False):
    return {"name": name, "tags": tags or ["cultural"], "indoor": indoor}


def _slot_dict(time="09:00", activity_name="Senso-ji Temple", is_alternative=False):
    return {
        "start_time": time,
        "activity": _activity_dict(activity_name),
        "is_alternative": is_alternative,
    }


def _day_dict(day_num=1, location="Tokyo", is_arrival=False, is_departure=False, slots=None):
    return {
        "day_num": day_num,
        "location": location,
        "is_arrival": is_arrival,
        "is_departure": is_departure,
        "slots": slots or [_slot_dict()],
    }


def _itinerary_json(
    destinations=None,
    start_date="2026-06-20",
    days=None,
    activity_updates=None,
):
    destinations = destinations or ["Tokyo"]
    days = days or [
        _day_dict(1, "Tokyo", is_arrival=True),
        _day_dict(2, "Tokyo"),
    ]
    return json.dumps({
        "itinerary": {
            "destinations": destinations,
            "start_date": start_date,
            "days": days,
        },
        "activity_updates": activity_updates if activity_updates is not None else {},
    })


def _empty_itinerary_json(destinations=None):
    return json.dumps({
        "itinerary": {
            "destinations": destinations or ["Tokyo"],
            "start_date": "2026-06-20",
            "days": [],
        },
        "activity_updates": {},
    })


def _seed_full_research(ks: KnowledgeState, destination: str, depth: str = "full") -> None:
    ks.update_research(destination, DestinationResearch(
        name=destination, country="Japan", depth=depth,
        vibe="vibrant city", summary="great city",
    ))


def _make_wrapper(ks=None, user_context="", destinations_with_research=None):
    ks = ks or KnowledgeState()
    for dest in (destinations_with_research or ["Tokyo"]):
        _seed_full_research(ks, dest)
    llm = make_llm()
    llm.chat.return_value = stop_msg(_itinerary_json())
    specialist = ItineraryPlannerSpecialist(llm, [])
    uc = UserContext(user_context)
    return ItineraryPlannerWrapperTool(specialist, ks, uc), specialist, ks, llm


# ---------------------------------------------------------------------------
# Pre-flight research validation
# ---------------------------------------------------------------------------

def test_itinerary_wrapper_returns_error_when_research_missing():
    ks = KnowledgeState()
    llm = make_llm()
    wrapper = ItineraryPlannerWrapperTool(ItineraryPlannerSpecialist(llm, []), ks, UserContext())
    result = wrapper.execute(query="10 days Tokyo", destinations=["Tokyo"])
    assert result["status"] == "error"
    assert "Tokyo" in result["summary"]
    llm.chat.assert_not_called()


def test_itinerary_wrapper_returns_error_listing_all_missing_destinations():
    ks = KnowledgeState()
    _seed_full_research(ks, "Kyoto")  # only Kyoto has full research
    llm = make_llm()
    wrapper = ItineraryPlannerWrapperTool(ItineraryPlannerSpecialist(llm, []), ks, UserContext())
    result = wrapper.execute(query="2 weeks Japan", destinations=["Tokyo", "Kyoto", "Osaka"])
    assert result["status"] == "error"
    assert "Tokyo" in result["summary"]
    assert "Osaka" in result["summary"]
    assert "Kyoto" not in result["summary"]
    llm.chat.assert_not_called()


def test_itinerary_wrapper_returns_error_for_light_depth_research():
    ks = KnowledgeState()
    _seed_full_research(ks, "Tokyo", depth="light")
    llm = make_llm()
    wrapper = ItineraryPlannerWrapperTool(ItineraryPlannerSpecialist(llm, []), ks, UserContext())
    result = wrapper.execute(query="10 days Tokyo", destinations=["Tokyo"])
    assert result["status"] == "error"
    assert "Tokyo" in result["summary"]
    llm.chat.assert_not_called()


# ---------------------------------------------------------------------------
# ItineraryPlannerWrapperTool — happy path
# ---------------------------------------------------------------------------

def test_itinerary_wrapper_calls_update_itinerary():
    wrapper, _, ks, _ = _make_wrapper()
    wrapper.execute(query="10 days Tokyo", destinations=["Tokyo"])
    key = frozenset(["Tokyo"])
    assert key in ks.itineraries
    assert ks.itineraries[key].destinations == ["Tokyo"]


def test_itinerary_wrapper_calls_update_activities_for_non_empty():
    wrapper, _, ks, llm = _make_wrapper()
    llm.chat.return_value = stop_msg(_itinerary_json(
        activity_updates={"Tokyo": [{"name": "teamLab Planets", "tags": ["art", "indoor"], "indoor": True}]},
    ))
    wrapper.execute(query="10 days Tokyo", destinations=["Tokyo"])
    activities = ks.destinations["Tokyo"].research.activities
    assert activities is not None
    assert any(a.name == "teamLab Planets" for a in activities)


def test_itinerary_wrapper_skips_update_activities_when_empty():
    wrapper, _, ks, _ = _make_wrapper()
    wrapper.execute(query="10 days Tokyo", destinations=["Tokyo"])
    # activity_updates={} — update_activities must not touch research.activities
    assert ks.destinations["Tokyo"].research.activities is None


def test_itinerary_wrapper_exception_returns_error():
    wrapper, specialist, ks, _ = _make_wrapper()
    specialist.run = MagicMock(side_effect=RuntimeError("LLM unavailable"))
    result = wrapper.execute(query="10 days Tokyo", destinations=["Tokyo"])
    assert result["status"] == "error"
    assert frozenset(["Tokyo"]) not in ks.itineraries


def test_itinerary_wrapper_retries_when_itinerary_has_no_days():
    wrapper, _, ks, llm = _make_wrapper()
    llm.chat.side_effect = [
        stop_msg(_empty_itinerary_json()),  # first attempt — no days
        stop_msg(_itinerary_json()),         # retry — full itinerary
    ]
    result = wrapper.execute(query="10 days Tokyo", destinations=["Tokyo"])
    assert result["status"] == "ok"
    assert llm.chat.call_count >= 2
    assert frozenset(["Tokyo"]) in ks.itineraries


def test_itinerary_wrapper_errors_when_still_empty_after_retry():
    wrapper, _, ks, llm = _make_wrapper()
    llm.chat.return_value = stop_msg(_empty_itinerary_json())
    result = wrapper.execute(query="10 days Tokyo", destinations=["Tokyo"])
    assert result["status"] == "error"
    assert "two attempts" in result["summary"]
    assert frozenset(["Tokyo"]) not in ks.itineraries


def test_itinerary_wrapper_summary_includes_all_slots():
    wrapper, _, ks, _ = _make_wrapper()
    result = wrapper.execute(query="10 days Tokyo", destinations=["Tokyo"])
    assert result["status"] == "ok"
    assert "Day 1" in result["summary"]
    assert "Day 2" in result["summary"]
    assert "Senso-ji Temple" in result["summary"]


