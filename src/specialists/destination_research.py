import json
import re

from agent.harness import SimpleReActAgent
from agent.prompts.destination_research import DESTINATION_RESEARCH_PROMPT
from clients.llm_client import LLMClient
from config.specialist_tuning import resolve_tuning
from notifications import ProgressNotifier
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

    def __init__(self, llm_client: LLMClient, tools: list[BaseTool], debug: bool = False, progress_notifier: ProgressNotifier | None = None):
        tuning = resolve_tuning("destination_research", llm_client.model)
        self._default_max_iterations = tuning.max_iterations
        self._agent = SimpleReActAgent(
            llm_client=llm_client,
            tools=tools,
            system_prompt=DESTINATION_RESEARCH_PROMPT,
            max_iterations=tuning.max_iterations,
            debug=debug,
            extra_body=tuning.extra_body,
            timeout=tuning.timeout_s,
            progress_notifier=progress_notifier,
        )
        self._last_run_max_iterations: int | None = None

    def run(
        self,
        destination: str,
        depth: str,
        user_context: str,
        max_iterations: int | None = None,
        existing_research: DestinationResearch | None = None,
    ) -> DestinationResearch:
        max_iterations = max_iterations if max_iterations is not None else self._default_max_iterations
        self._last_run_max_iterations = max_iterations
        self._agent._max_iterations = max_iterations

        task = (
            f"destination: `{destination}`\n"
            f"depth: {depth}\n"
            f"user context: {user_context or '(none)'}"
        )
        if existing_research is not None:
            task += (
                f"\nexisting research:\n"
                f"{existing_research.model_dump_json(indent=2)}"
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
