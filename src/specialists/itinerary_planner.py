import json
import re
from datetime import date

from pydantic import ValidationError

from agent.harness import SimpleReActAgent
from agent.prompts.itinerary_planner import ITINERARY_PLANNER_PROMPT
from clients.llm_client import LLMClient
from models.specialist_outputs import ItineraryPlannerOutput
from tools.base import BaseTool


def _parse_itinerary_output(text: str) -> ItineraryPlannerOutput:
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        try:
            return ItineraryPlannerOutput(**data)
        except ValidationError as e:
            raise ValueError(f"ItineraryPlannerOutput validation failed: {e}") from e

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            try:
                return ItineraryPlannerOutput(**data)
            except ValidationError as e:
                raise ValueError(f"ItineraryPlannerOutput validation failed: {e}") from e

    raise ValueError(f"Could not parse ItineraryPlannerOutput from: {text[:200]!r}")


class ItineraryPlannerSpecialist:
    def __init__(self, llm_client: LLMClient, tools: list[BaseTool], debug: bool = False, reasoning_effort: str | None = None):
        self._agent = SimpleReActAgent(
            llm_client=llm_client,
            tools=tools,
            system_prompt=ITINERARY_PLANNER_PROMPT,
            max_iterations=6,
            debug=debug,
            reasoning_effort=reasoning_effort,
        )
        self._last_run_context: str | None = None

    def run(
        self,
        query: str,
        context: str = "",
        max_iterations: int = 6,
    ) -> ItineraryPlannerOutput:
        self._last_run_context = context
        self._agent._max_iterations = max_iterations
        task = f"Today: {date.today().isoformat()}\n\n" + (query if not context else f"{query}\n\n{context}")
        raw = self._agent.run(task)
        return _parse_itinerary_output(raw)
