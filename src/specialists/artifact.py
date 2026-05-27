import json
import re

from pydantic import ValidationError

from agent.harness import SimpleReActAgent
from agent.prompts.artifact import ARTIFACT_PROMPT
from clients.llm_client import LLMClient
from models.specialist_outputs import ArtifactOutput
from tools.base import BaseTool


def _parse_artifact_output(text: str) -> ArtifactOutput:
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        try:
            return ArtifactOutput(**data)
        except ValidationError as e:
            raise ValueError(f"ArtifactOutput validation failed: {e}") from e

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            try:
                return ArtifactOutput(**data)
            except ValidationError as e:
                raise ValueError(f"ArtifactOutput validation failed: {e}") from e

    raise ValueError(f"Could not parse ArtifactOutput from: {text[:200]!r}")


class ArtifactSpecialist:
    def __init__(self, llm_client: LLMClient, tools: list[BaseTool], debug: bool = False):
        self._agent = SimpleReActAgent(
            llm_client=llm_client,
            tools=tools,
            system_prompt=ARTIFACT_PROMPT,
            max_iterations=3,
            debug=debug,
        )
        self._last_run_context: str | None = None

    def run(self, query: str, context: str = "") -> ArtifactOutput:
        self._last_run_context = context
        task = query if not context else f"{query}\n\n{context}"
        raw = self._agent.run(task)
        return _parse_artifact_output(raw)
