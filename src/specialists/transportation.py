import json
import re
from datetime import date

from pydantic import ValidationError

from agent.harness import SimpleReActAgent
from agent.prompts.transportation import TRANSPORTATION_PROMPT
from clients.llm_client import LLMClient
from config.specialist_tuning import resolve_tuning
from notifications import ProgressNotifier
from models.knowledge_state import DateRange, RouteKey, TravelOption
from tools.base import BaseTool


def _parse_travel_options(text: str) -> list[TravelOption]:
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()

    def _build(data: list) -> list[TravelOption]:
        results: list[TravelOption] = []
        errors: list[str] = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                errors.append(f"item {i}: expected dict, got {type(item).__name__}")
                continue
            try:
                results.append(TravelOption(**item))
            except ValidationError as e:
                label = (
                    f"Mode: {item.get('mode', '?')}, "
                    f"Origin: {item.get('origin', '?')}, "
                    f"Destination: {item.get('destination', '?')}"
                )
                errors.append(f"item {i} ({label}): {e}")
        if errors:
            raise ValueError(
                f"{len(errors)} of {len(data)} TravelOption(s) failed to parse:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )
        return results

    # json.JSONDecodeError is a subclass of ValueError, but _build's ValueError is
    # not a JSONDecodeError — catching only JSONDecodeError lets _build errors propagate.
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return _build(data)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, list):
                return _build(data)
        except json.JSONDecodeError:
            pass

    return []


class TransportationSpecialist:
    def __init__(self, llm_client: LLMClient, tools: list[BaseTool], debug: bool = False, progress_notifier: ProgressNotifier | None = None):
        tuning = resolve_tuning("transportation", llm_client.model)
        self._default_max_iterations = tuning.max_iterations
        self._agent = SimpleReActAgent(
            llm_client=llm_client,
            tools=tools,
            system_prompt=TRANSPORTATION_PROMPT,
            max_iterations=tuning.max_iterations,
            debug=debug,
            extra_body=tuning.extra_body,
            timeout=tuning.timeout_s,
            progress_notifier=progress_notifier,
        )
        self._last_run_max_iterations: int | None = None

    def run(
        self,
        route_key: RouteKey,
        date_range: DateRange,
        user_context: str = "",
        existing_edges: str | None = None,
        max_iterations: int | None = None,
        trip_type: str = "one_way",
    ) -> list[TravelOption]:
        max_iterations = max_iterations if max_iterations is not None else self._default_max_iterations
        self._last_run_max_iterations = max_iterations
        self._agent._max_iterations = max_iterations

        route_str = f"`{route_key.origin}` → `{route_key.destination}` ({date_range.label})"

        lines = [
            f"Today: {date.today().isoformat()}",
            f"trip_type: {trip_type}",
            f"route: {route_str}",
        ]

        if user_context:
            lines.append(f"user context: {user_context}")

        if existing_edges:
            lines.append("existing edges:")
            lines.append(existing_edges)

        response = self._agent.run("\n".join(lines))
        return _parse_travel_options(response)
