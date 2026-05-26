import json
import re

from pydantic import ValidationError

from agent.harness import SimpleReActAgent
from agent.prompts.budget import BUDGET_PROMPT
from clients.llm_client import LLMClient
from models.budget import BudgetSpecialistOutput
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
    def __init__(self, llm_client: LLMClient, tools: list[BaseTool]):
        self._agent = SimpleReActAgent(
            llm_client=llm_client,
            tools=tools,
            system_prompt=BUDGET_PROMPT,
            max_iterations=5,
        )
        self._last_run_max_iterations: int | None = None
        self._last_run_context: str | None = None

    def run(
        self,
        query: str,
        context: str = "",
        max_iterations: int = 5,
    ) -> BudgetSpecialistOutput:
        self._last_run_max_iterations = max_iterations
        self._last_run_context = context
        self._agent._max_iterations = max_iterations

        task = query
        if context:
            task = f"{query}\n\n{context}"

        raw = self._agent.run(task)
        return _parse_budget_output(raw)
