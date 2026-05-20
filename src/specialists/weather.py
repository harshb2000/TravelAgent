import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent.prompts.weather import WEATHER_PROMPT
from clients.llm_client import LLMClient
from models.knowledge_state import KnowledgeState, DateRange
from models.weather import WeatherOutput, DailyWeather
from tools.base import BaseTool


class WeatherSpecialist:
    """
    Stateless single-LLM-call specialist. One call to decide which tools to
    fire, then Python executes them, merges if needed, and writes to
    KnowledgeState. The LLM never outputs structured weather data.

    No ConversationHistory — the wrapper passes all relevant KnowledgeState
    context explicitly on each call, so history adds nothing here.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        tools: list[BaseTool],
        knowledge: KnowledgeState,
    ):
        self._llm = llm_client
        self._knowledge = knowledge
        self._tool_map = {t.name: t for t in tools}
        self._tool_defs = [t.to_llm_definition() for t in tools] or None

    def run(
        self,
        destination: str,
        date_range: str,
        existing_entries: dict | None = None,
    ) -> None:
        """
        Fetch weather for `destination` over `date_range` and write to KnowledgeState.
        Raises ValueError on failure so the wrapper can return an error string.
        """
        target_dr = DateRange.from_string(date_range)

        task = f"Get weather for {destination} for date range: {date_range}"
        if existing_entries:
            task += "\n\nExisting entries (use slice_weather_range to avoid redundant API calls):"
            for label, summary in existing_entries.items():
                task += f"\n  {label}: {summary}"

        messages = [
            {"role": "system", "content": WEATHER_PROMPT},
            {"role": "user", "content": task},
        ]
        msg = self._llm.chat(messages, tools=self._tool_defs)

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            raise ValueError("WeatherSpecialist: LLM returned no tool calls")

        results = self._dispatch(tool_calls)

        weather_payloads: list[dict] = []
        for _, content in results:
            data = json.loads(content)
            if data.get("status") == "error":
                raise ValueError(f"WeatherSpecialist tool error: {data.get('error')}")
            if "days" in data and "mode" in data:
                weather_payloads.append(data)

        if not weather_payloads:
            raise ValueError("WeatherSpecialist: no weather data returned by tools")

        try:
            if len(weather_payloads) == 1:
                wo = WeatherOutput(**weather_payloads[0])
            else:
                all_days = [
                    DailyWeather(**d)
                    for payload in weather_payloads
                    for d in payload["days"]
                ]
                all_days.sort(key=lambda d: d.date)
                wo = WeatherOutput(mode=weather_payloads[0]["mode"], city=destination, days=all_days)
        except Exception as e:
            raise ValueError(f"WeatherSpecialist: tool returned malformed weather data — {e}") from e

        self._knowledge.update_weather(destination, target_dr, wo)

    def _dispatch(self, tool_calls: list[dict]) -> list[tuple[str, str]]:
        def run_one(tc: dict) -> tuple[str, str]:
            call_id = tc["id"]
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                args = {}
            tool = self._tool_map.get(name)
            if tool is None:
                result = {"status": "error", "error": f"unknown tool: {name}"}
            else:
                try:
                    result = tool.execute(**args)
                except Exception as e:
                    result = {"status": "error", "error": str(e)}
            return call_id, json.dumps(result)

        if len(tool_calls) == 1:
            return [run_one(tool_calls[0])]

        results: dict[str, str] = {}
        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(run_one, tc): tc["id"] for tc in tool_calls}
            for future in as_completed(futures):
                call_id, content = future.result()
                results[call_id] = content
        return [(tc["id"], results[tc["id"]]) for tc in tool_calls]
