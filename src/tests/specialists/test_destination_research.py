import json
import pytest
from unittest.mock import MagicMock

from tests.helpers import make_llm, stop_msg, tool_call_msg
from models.knowledge_state import KnowledgeState, DestinationResearch, UserContext
from specialists.destination_research import DestinationResearchSpecialist
from tools.destination_research_wrapper import DestinationResearchWrapperTool


def _light_json(name: str = "Tokyo") -> str:
    return json.dumps({
        "name": name, "country": "Japan", "depth": "light",
        "vibe": "Vibrant megacity blending ancient temples with modern skyscrapers.",
        "top_attractions": ["Shibuya Crossing", "Senso-ji Temple"],
        "summary": f"{name} offers an exceptional mix of tradition and modernity.",
    })


def _full_json(name: str = "Tokyo") -> str:
    return json.dumps({
        "name": name, "country": "Japan", "depth": "full",
        "vibe": "Vibrant megacity with deep cultural roots.",
        "top_attractions": ["Shibuya Crossing", "Senso-ji Temple", "Tsukiji Market"],
        "summary": f"{name} is a world-class destination suited to all travel styles.",
        "safety_summary": {"text": "Very safe, low crime", "source_url": "https://example.com"},
        "festivals": ["Cherry Blossom (late March–April)"],
        "neighbourhoods": {"Shinjuku": {"text": "Shopping and nightlife hub", "source_url": "https://example.com"}},
        "visa_complexity": {"Indian passport": {"text": "Advance visa required, ~7 days", "source_url": "https://example.com"}},
        "activities": [{"name": "Shibuya Crossing", "tags": ["iconic"], "indoor": False, "duration_min": 30, "source_url": None}],
    })


def _make_wrapper(depth_in_ks: str | None = None, destination: str = "Tokyo"):
    ks = KnowledgeState()
    llm = make_llm()
    llm.chat.return_value = stop_msg(_full_json() if depth_in_ks != "light" else _light_json())
    if depth_in_ks:
        ks.update_research(destination, DestinationResearch(
            name=destination, country="Japan", depth=depth_in_ks,
            summary=f"Existing {depth_in_ks} research summary.",
            vibe="Vibrant city.", top_attractions=["Shibuya"],
        ))
    specialist = DestinationResearchSpecialist(llm, [])
    return DestinationResearchWrapperTool(specialist, ks, UserContext()), specialist, ks, llm


# ---- Specialist.run() ----

def test_destination_research_run_returns_typed_result():
    llm = make_llm()
    llm.chat.return_value = stop_msg(_light_json())
    result = DestinationResearchSpecialist(llm, []).run("Tokyo", "light", "", max_iterations=1)
    assert result.name == "Tokyo"
    assert result.depth == "light"
    assert result.summary != ""
    assert len(result.top_attractions) == 2
    assert result.safety_summary is None
    assert result.visa_complexity is None



# ---- Wrapper pre-firing checks ----

def test_destination_research_wrapper_light_cache_hit():
    wrapper, _, _, llm = _make_wrapper(depth_in_ks="light")
    result = wrapper.execute(destination="Tokyo", depth="light")
    llm.chat.assert_not_called()
    assert result["summary"] == "Existing light research summary."


def test_destination_research_wrapper_full_as_superset_of_light():
    wrapper, _, _, llm = _make_wrapper(depth_in_ks="full")
    result = wrapper.execute(destination="Tokyo", depth="light")
    llm.chat.assert_not_called()
    assert result["summary"] == "Existing full research summary."


def test_destination_research_wrapper_upgrade_uses_3_iterations():
    wrapper, specialist, _, llm = _make_wrapper(depth_in_ks="light")
    wrapper.execute(destination="Tokyo", depth="full")
    llm.chat.assert_called()
    assert specialist._last_run_max_iterations == 3


def test_destination_research_wrapper_passthrough_uses_4_iterations():
    wrapper, specialist, _, llm = _make_wrapper(depth_in_ks="full")
    wrapper.execute(destination="Tokyo", depth="full")
    llm.chat.assert_called()
    assert specialist._last_run_max_iterations == 4


def test_destination_research_wrapper_full_miss_light_uses_1_iteration():
    wrapper, specialist, _, llm = _make_wrapper(depth_in_ks=None)
    llm.chat.return_value = stop_msg(_light_json())
    wrapper.execute(destination="Tokyo", depth="light")
    assert specialist._last_run_max_iterations == 1


def test_destination_research_wrapper_calls_update_research():
    wrapper, _, ks, llm = _make_wrapper(depth_in_ks=None)
    llm.chat.return_value = stop_msg(_light_json())
    wrapper.execute(destination="Tokyo", depth="light")
    assert ks.destinations["Tokyo"].research is not None
    assert ks.destinations["Tokyo"].research.name == "Tokyo"


def test_destination_research_wrapper_returns_summary_verbatim():
    wrapper, _, _, llm = _make_wrapper(depth_in_ks=None)
    llm.chat.return_value = stop_msg(_light_json())
    result = wrapper.execute(destination="Tokyo", depth="light")
    assert result["summary"] == "Tokyo offers an exceptional mix of tradition and modernity."


def test_destination_research_wrapper_exception_returns_error():
    wrapper, specialist, ks, _ = _make_wrapper(depth_in_ks=None)
    specialist.run = MagicMock(side_effect=RuntimeError("network error"))
    result = wrapper.execute(destination="Tokyo", depth="light")
    assert result["status"] == "error"
    assert "Tokyo" not in ks.destinations
