from unittest.mock import MagicMock

from tests.helpers import make_llm, stop_msg, tool_call_msg
from models.knowledge_state import KnowledgeState, UserContext, DestinationCandidate
from specialists.explorer import ExplorerSpecialist
from specialists.weather import WeatherSpecialist
from specialists.destination_research import DestinationResearchSpecialist
from specialists.transportation import TransportationSpecialist
from specialists.budget import BudgetSpecialist
from specialists.itinerary_planner import ItineraryPlannerSpecialist
from specialists.artifact import ArtifactSpecialist
from agent.orchestrator import Orchestrator


def _make_mock_specialists() -> dict:
    return {
        "explorer": MagicMock(spec=ExplorerSpecialist),
        "weather": MagicMock(spec=WeatherSpecialist),
        "destination_research": MagicMock(spec=DestinationResearchSpecialist),
        "transportation": MagicMock(spec=TransportationSpecialist),
        "budget": MagicMock(spec=BudgetSpecialist),
        "itinerary_planner": MagicMock(spec=ItineraryPlannerSpecialist),
        "artifact": MagicMock(spec=ArtifactSpecialist),
    }


def test_specialist_tool_call_dispatches_to_specialist_and_updates_knowledge():
    llm = make_llm()
    user_context = UserContext()
    knowledge = KnowledgeState()
    specialists = _make_mock_specialists()

    specialists["explorer"].run.return_value = [
        DestinationCandidate(
            name="Bali", country="Indonesia", vibe_tags=["beach"],
            rationale="Tropical paradise", source_url="", query="beach SEA",
        ),
    ]

    llm.chat.side_effect = [
        tool_call_msg([{"id": "c1", "name": "explorer", "args": {"query": "beach trips SEA", "max_results": 5}}]),
        stop_msg("Found some destinations!"),
    ]

    orchestrator = Orchestrator(llm, user_context, knowledge, specialists)
    orchestrator.turn("Find me beach destinations in SEA")

    specialists["explorer"].run.assert_called_once()
    assert any(c.name == "Bali" for c in knowledge.candidates)


def test_turn_builds_task_with_user_context_and_input():
    llm = make_llm()
    user_context = UserContext()
    user_context.context = "Beach trip in SEA"
    knowledge = KnowledgeState()

    llm.chat.return_value = stop_msg("Here are some options!")

    orchestrator = Orchestrator(llm, user_context, knowledge, _make_mock_specialists())
    orchestrator.turn("What should I know about Bali?")

    messages = llm.chat.call_args.args[0]
    all_user_content = " ".join(m["content"] for m in messages if m["role"] == "user" and m.get("content"))

    assert "Beach trip in SEA" in all_user_content
    assert "What should I know about Bali?" in all_user_content


