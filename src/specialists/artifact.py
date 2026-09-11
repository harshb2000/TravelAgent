import json
import re

from pydantic import ValidationError

from agent.harness import SimpleReActAgent
from agent.prompts.artifact import ARTIFACT_PROMPT
from clients.llm_client import LLMClient
from config.specialist_tuning import resolve_tuning
from notifications import ProgressNotifier
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
    def __init__(self, llm_client: LLMClient, tools: list[BaseTool], debug: bool = False, progress_notifier: ProgressNotifier | None = None):
        tuning = resolve_tuning("artifact", llm_client.model)
        self._agent = SimpleReActAgent(
            llm_client=llm_client,
            tools=tools,
            system_prompt=ARTIFACT_PROMPT,
            max_iterations=tuning.max_iterations,
            debug=debug,
            extra_body=tuning.extra_body,
            timeout=tuning.timeout_s,
            progress_notifier=progress_notifier,
        )
        self._last_run_task: str | None = None

    def run(self, query: str, knowledge: str = "") -> ArtifactOutput:
        lines = [f"query: {query}"]
        if knowledge:
            lines.append(f"knowledge:\n{knowledge}")
        self._last_run_task = "\n".join(lines)
        raw = self._agent.run(self._last_run_task)
        return _parse_artifact_output(raw)
