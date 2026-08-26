import json
import re
from datetime import date

from pydantic import ValidationError

from agent.harness import SimpleReActAgent
from agent.prompts.budget import BUDGET_PROMPT
from clients.llm_client import LLMClient
from config.specialist_tuning import resolve_tuning
from models.knowledge_state import DestinationBudget
from models.specialist_outputs import BudgetSpecialistOutput
from tools.base import BaseTool


def _parse_budget_output(text: str) -> BudgetSpecialistOutput:
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        try:
            return BudgetSpecialistOutput(**data)
        except ValidationError as e:
            raise ValueError(f"BudgetSpecialistOutput validation failed: {e}") from e

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            try:
                return BudgetSpecialistOutput(**data)
            except ValidationError as e:
                raise ValueError(f"BudgetSpecialistOutput validation failed: {e}") from e

    raise ValueError(f"Could not parse BudgetSpecialistOutput from: {text[:200]!r}")


class BudgetSpecialist:
    def __init__(self, llm_client: LLMClient, tools: list[BaseTool], debug: bool = False):
        tuning = resolve_tuning("budget", llm_client.model)
        self._default_max_iterations = tuning.max_iterations
        self._agent = SimpleReActAgent(
            llm_client=llm_client,
            tools=tools,
            system_prompt=BUDGET_PROMPT,
            max_iterations=tuning.max_iterations,
            debug=debug,
            extra_body=tuning.extra_body,
            timeout=tuning.timeout_s,
        )
        self._last_run_max_iterations: int | None = None
        self._last_run_task: str | None = None

    def run(
        self,
        query: str,
        user_context: str = "",
        existing_budget: DestinationBudget | None = None,
        travel_costs: str | None = None,
        max_iterations: int | None = None,
    ) -> BudgetSpecialistOutput:
        max_iterations = max_iterations if max_iterations is not None else self._default_max_iterations
        self._last_run_max_iterations = max_iterations
        self._agent._max_iterations = max_iterations

        lines = [
            f"Today: {date.today().isoformat()}",
            f"query: {query}",
        ]
        if user_context:
            lines.append(f"user context: {user_context}")
        if existing_budget is not None:
            lines.append(f"existing budget:\n{existing_budget.model_dump_json(indent=2)}")
        if travel_costs:
            lines.append(f"travel costs:\n{travel_costs}")

        self._last_run_task = "\n".join(lines)
        raw = self._agent.run(self._last_run_task)
        return _parse_budget_output(raw)
