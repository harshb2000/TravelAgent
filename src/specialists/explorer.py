import json
import re

from agent.harness import SimpleReActAgent
from agent.prompts.explorer import EXPLORER_PROMPT
from clients.llm_client import LLMClient
from models.knowledge_state import DestinationCandidate
from tools.base import BaseTool


# Minimum Jaccard similarity between a cached candidate's wordset and the incoming
# query's positive wordset for the candidate to count as a cache hit.
# Short-text Jaccard is naturally low (candidate wordsets include the destination name
# which rarely appears in the query), so a lenient threshold is appropriate.
EXPLORER_CACHE_THRESHOLD = 0.3


def _parse_candidates(text: str) -> list[DestinationCandidate]:
    """Extract a JSON array from LLM response and parse into DestinationCandidates."""
    # Strip markdown code fences if the LLM wrapped the output
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()

    def _build(data: list) -> list[DestinationCandidate]:
        results = []
        for item in data:
            if not isinstance(item, dict):
                continue
            item.pop("added_at", None)  # system-managed; ignore if LLM included it
            try:
                results.append(DestinationCandidate(**item))
            except Exception:
                pass
        return results

    # Try direct parse first
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return _build(data)
    except json.JSONDecodeError:
        pass

    # Fallback: extract first JSON array found anywhere in the text
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, list):
                return _build(data)
        except json.JSONDecodeError:
            pass

    return []


class ExplorerSpecialist:
    def __init__(self, llm_client: LLMClient, tools: list[BaseTool], debug: bool = False, reasoning_effort: str | None = None):
        self._agent = SimpleReActAgent(
            llm_client=llm_client,
            tools=tools,
            system_prompt=EXPLORER_PROMPT,
            max_iterations=3,
            debug=debug,
            reasoning_effort=reasoning_effort,
        )
        # Exposed for wrapper tests — record what was passed on the last run
        self._last_run_max_results: int | None = None
        self._last_run_query: str | None = None
        self._last_run_user_context: str | None = None

    def run(
        self,
        query: str,
        max_results: int = 5,
        existing_candidates: list[DestinationCandidate] | None = None,
        user_context: str = "",
    ) -> list[DestinationCandidate]:
        self._last_run_max_results = max_results
        self._last_run_query = query
        self._last_run_user_context = user_context

        lines = [f"Find up to {max_results} destination candidates for: {query}"]
        if user_context:
            lines.append(f"\nUser context: {user_context}")
        if existing_candidates:
            names = [c.name for c in existing_candidates]
            lines.append(f"Already suggested (do not repeat): {', '.join(names)}")
        lines.append(f"\nReturn a JSON array of up to {max_results} candidates.")

        response = self._agent.run("\n".join(lines))
        return _parse_candidates(response)
