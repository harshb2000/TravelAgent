import json
import re

from agent.harness import SimpleReActAgent
from agent.prompts.destination_research import DESTINATION_RESEARCH_PROMPT
from clients.llm_client import LLMClient
from models.knowledge_state import DestinationResearch
from tools.base import BaseTool


def _parse_destination_research(text: str) -> DestinationResearch | None:
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()
    try:
        return DestinationResearch(**json.loads(cleaned))
    except Exception:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return DestinationResearch(**json.loads(match.group()))
        except Exception:
            pass
    return None


class DestinationResearchSpecialist:
    """
    Uses SimpleReActAgent — ConversationHistory persists across session calls
    so prior searches for a destination are visible on follow-up calls (e.g.
    upgrading from light to full depth without re-fetching basic info).
    """

    def __init__(self, llm_client: LLMClient, tools: list[BaseTool], debug: bool = False, reasoning_effort: str | None = None):
        self._agent = SimpleReActAgent(
            llm_client=llm_client,
            tools=tools,
            system_prompt=DESTINATION_RESEARCH_PROMPT,
            max_iterations=4,
            debug=debug,
            reasoning_effort=reasoning_effort,
        )
        self._last_run_max_iterations: int | None = None

    def run(
        self,
        destination: str,
        depth: str,
        user_context: str,
        max_iterations: int = 4,
    ) -> DestinationResearch:
        self._last_run_max_iterations = max_iterations
        self._agent._max_iterations = max_iterations

        task = (
            f"Research {destination} at depth='{depth}'.\n\n"
            f"UserContext: {user_context or '(none provided)'}\n\n"
            f"Return a JSON object matching the DestinationResearch schema."
        )
        response = self._agent.run(task)

        try:
            result = _parse_destination_research(response)
        except Exception as e:
            raise ValueError(f"DestinationResearchSpecialist: malformed output — {e}") from e

        if result is None:
            raise ValueError(
                f"DestinationResearchSpecialist: unparseable output — {response[:200]}"
            )
        return result
