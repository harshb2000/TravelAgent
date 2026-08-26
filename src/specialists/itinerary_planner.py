import json
import re
from datetime import date

from pydantic import ValidationError

from agent.harness import SimpleReActAgent
from agent.prompts.itinerary_planner import ITINERARY_PLANNER_PROMPT
from clients.llm_client import LLMClient
from config.specialist_tuning import resolve_tuning
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
    def __init__(self, llm_client: LLMClient, tools: list[BaseTool], debug: bool = False):
        tuning = resolve_tuning("itinerary_planner", llm_client.model)
        self._default_max_iterations = tuning.max_iterations
        self._agent = SimpleReActAgent(
            llm_client=llm_client,
            tools=tools,
            system_prompt=ITINERARY_PLANNER_PROMPT,
            max_iterations=tuning.max_iterations,
            debug=debug,
            extra_body=tuning.extra_body,
            timeout=tuning.timeout_s,
        )

    def run(
        self,
        query: str,
        user_context: str = "",
        destination_research: str | None = None,
        weather: str | None = None,
        max_iterations: int | None = None,
    ) -> ItineraryPlannerOutput:
        max_iterations = max_iterations if max_iterations is not None else self._default_max_iterations
        self._agent._max_iterations = max_iterations

        lines = [
            f"Today: {date.today().isoformat()}",
            f"query: {query}",
        ]
        if user_context:
            lines.append(f"user context: {user_context}")
        if destination_research:
            lines.append(f"destination research:\n{destination_research}")
        if weather:
            lines.append(f"weather:\n{weather}")

        raw = self._agent.run("\n".join(lines))
        return _parse_itinerary_output(raw)
