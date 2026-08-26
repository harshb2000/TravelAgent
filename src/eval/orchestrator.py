#!/usr/bin/env python3
"""
Assertion-based evaluation for Orchestrator.

Section 1: Query routing (specialist selection, KS reuse, parallelisation)
Section 2: Specialist argument quality and error handling
Section 3: Clarification behaviour
Section 4: update_user_context accuracy
Section 5: User-facing response quality

Tests use the real Orchestrator with real specialists and real APIs.
KnowledgeState is pre-built synthetically where preconditions are needed.

Error-injection tests patch a single wrapper tool's execute method via
_patch(orchestrator, tool_name, response_or_sequence) — all other specialists
remain real. _Sequence lets the patched tool return different responses across
successive calls, enabling the re-invocation paths (IP5, AR2, W4/W5, etc.)
to be exercised deterministically without stubs.

Usage (from src/):
    python eval/orchestrator.py [filter ...]

Results saved to:
    src/eval/results/orchestrator/<timestamp>.json
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.orchestrator import Orchestrator
from clients.currency_client import CurrencyClient
from clients.llm_client import LLMClient
from clients.search_client import SearchClient
from clients.serpapi_client import SerpApiClient
from clients.weather_client import WeatherClient
from config.settings import settings
from config.specialist_tuning import resolve_model_config
from models.knowledge_state import (
    Activity,
    DateRange,
    DestinationResearch,
    Itinerary,
    ItineraryDay,
    KnowledgeState,
    NotableArea,
    RouteKey,
    RouteKnowledge,
    StringWithAttribution,
    TimeSlot,
    TravelOption,
    UserContext,
)
from models.weather import DailyWeather, WeatherOutput
from specialists.artifact import ArtifactSpecialist
from specialists.budget import BudgetSpecialist
from specialists.destination_research import DestinationResearchSpecialist
from specialists.explorer import ExplorerSpecialist
from specialists.itinerary_planner import ItineraryPlannerSpecialist
from specialists.transportation import TransportationSpecialist
from specialists.weather import WeatherSpecialist
from tools.calculate import CalculateTool
from tools.climate_summary import ClimateSummaryTool
from tools.currency_convert import CurrencyConvertTool
from tools.file_write import FileWriteTool
from tools.flight_search import FlightSearchTool
from tools.get_compiled import (
    GetBudgetCompiledTool,
    GetCandidatesCompiledTool,
    GetResearchCompiledTool,
    GetRouteCompiledTool,
    GetWeatherCompiledTool,
)
from tools.get_itinerary import GetItineraryTool
from tools.itinerary_planner_wrapper import render_itinerary
from tools.self_critique import SelfCritiqueTool
from tools.slice_weather_range import SliceWeatherRangeTool
from tools.weather_forecast import WeatherForecastTool
from tools.web_search import WebSearchTool


_SPECIALIST_TOOLS = frozenset({
    "explorer", "destination_research", "weather",
    "transportation", "budget", "itinerary_planner", "artifact",
})

_INTERNAL_NAMES = [
    "ExplorerSpecialist", "WeatherSpecialist", "DestinationResearchSpecialist",
    "TransportationSpecialist", "BudgetSpecialist", "ItineraryPlannerSpecialist",
    "ArtifactSpecialist", "KnowledgeState", "SimpleReActAgent", "WrapperTool",
]


# ---------------------------------------------------------------------------
# Error injection helpers
# ---------------------------------------------------------------------------

class _Sequence:
    """Returns responses in order; repeats the last on exhaustion.

    Each element may be a dict (returned as-is) or a callable(**kwargs) -> dict
    (called with the tool's kwargs, allowing inspect-and-delegate patterns).
    """

    def __init__(self, *responses):
        self._responses = list(responses)
        self._i = 0

    def __call__(self, **kwargs) -> dict:
        r = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return r(**kwargs) if callable(r) else dict(r)


def _patch(orchestrator: Orchestrator, tool_name: str, response) -> None:
    """Replace a wrapper tool's execute with a fixed dict or _Sequence."""
    tool = orchestrator._agent._tools[tool_name]
    if callable(response) and not isinstance(response, dict):
        tool.execute = response
    else:
        tool.execute = lambda **_kw: dict(response)


# ---------------------------------------------------------------------------
# Orchestrator factory — mirrors main.py exactly
# ---------------------------------------------------------------------------

def _make_orchestrator(
    llm: LLMClient,
    search_client: SearchClient,
    serpapi_client: SerpApiClient,
    weather_client: WeatherClient,
    currency_client: CurrencyClient,
    knowledge: KnowledgeState | None = None,
    user_context: UserContext | None = None,
) -> Orchestrator:
    knowledge = knowledge or KnowledgeState()
    user_context = user_context or UserContext()

    web_search = WebSearchTool(search_client)
    flight_search = FlightSearchTool(serpapi_client)
    weather_forecast = WeatherForecastTool(weather_client)
    climate_summary = ClimateSummaryTool(weather_client)
    currency_convert = CurrencyConvertTool(currency_client)
    calculate = CalculateTool()
    slice_weather = SliceWeatherRangeTool(knowledge)

    get_research = GetResearchCompiledTool(knowledge)
    get_budget = GetBudgetCompiledTool(knowledge)
    get_weather_compiled = GetWeatherCompiledTool(knowledge)
    get_route = GetRouteCompiledTool(knowledge)
    get_candidates = GetCandidatesCompiledTool(knowledge)
    get_itinerary = GetItineraryTool(knowledge)
    self_critique = SelfCritiqueTool(llm)
    file_write = FileWriteTool()

    specialists = {
        "explorer": ExplorerSpecialist(llm, [web_search]),
        "weather": WeatherSpecialist(llm, [weather_forecast, climate_summary, slice_weather], knowledge),
        "destination_research": DestinationResearchSpecialist(llm, [web_search]),
        "transportation": TransportationSpecialist(llm, [web_search, flight_search]),
        "budget": BudgetSpecialist(llm, [web_search, currency_convert, calculate]),
        "itinerary_planner": ItineraryPlannerSpecialist(llm, [web_search]),
        "artifact": ArtifactSpecialist(
            llm,
            [get_research, get_budget, get_weather_compiled, get_route, get_candidates,
             get_itinerary, self_critique, file_write],
        ),
    }

    return Orchestrator(llm, user_context, knowledge, specialists)


# ---------------------------------------------------------------------------
# KnowledgeState builders
# ---------------------------------------------------------------------------

def _minimal_weather(dest: str, label: str = "June 2026") -> WeatherOutput:
    return WeatherOutput(
        mode="climate", city=dest,
        days=[DailyWeather(
            date="2026-06-15", temp_max=28.0, temp_min=22.0,
            precipitation_prob=None, precipitation_sum=2.0, weather_description="",
        )],
    )


def _ks_with_light_research(dest: str, country: str = "Japan") -> KnowledgeState:
    ks = KnowledgeState()
    ks.update_research(dest, DestinationResearch(
        name=dest, country=country, depth="light",
        vibe=f"{dest} is a vibrant destination blending tradition and modernity.",
        top_attractions=["Grand Temple", "Central Market"],
        summary=f"{dest} is worth visiting for its culture and food scene.",
    ))
    return ks


def _ks_with_full_research(dest: str, country: str = "Japan") -> KnowledgeState:
    ks = KnowledgeState()
    ks.update_research(dest, DestinationResearch(
        name=dest, country=country, depth="full",
        vibe=f"{dest} blends ancient tradition with modern energy.",
        top_attractions=["Grand Temple", "Central Market", "Old Quarter"],
        summary=f"{dest} is a must-visit destination with rich culture.",
        safety_summary=StringWithAttribution(text="Generally safe for tourists.", source_url=None),
        festivals=["Spring Festival (April)"],
        notable_areas={"Old Quarter": NotableArea(
            description="Historic district.", highlights=["Night Market"], source_url=None,
        )},
        activities=[
            Activity(name="Temple Visit", tags=["cultural"], indoor=False, duration_min=90),
            Activity(name="Street Food Tour", tags=["food"], indoor=False, duration_min=120),
        ],
    ))
    return ks


def _ks_with_full_research_and_weather(dest: str, country: str = "Japan") -> KnowledgeState:
    ks = _ks_with_full_research(dest, country)
    ks.update_weather(dest, DateRange.from_string("June 2026"), _minimal_weather(dest))
    return ks


def _ks_with_weather_only(dest: str, label: str = "June 2026") -> KnowledgeState:
    ks = KnowledgeState()
    ks.update_weather(dest, DateRange.from_string(label), _minimal_weather(dest, label))
    return ks


def _ks_with_ground_route(origin: str, dest: str) -> KnowledgeState:
    ks = KnowledgeState()
    dr = DateRange("any")
    option = TravelOption(
        mode="bus", origin=origin, destination=dest,
        duration_min=240, cost_usd=8.0, source_url=None,
    )
    ks.routes[RouteKey(origin, dest)] = RouteKnowledge(options={dr: [option]})
    return ks


# ---------------------------------------------------------------------------
# Synthetic tool response helpers (KS side-effect + realistic summary format)
# ---------------------------------------------------------------------------

def _weather_ok(dest: str, date_range_str: str, ks: KnowledgeState) -> dict:
    """Update KS and return a response matching WeatherWrapperTool._template_summary (climate)."""
    wo = WeatherOutput(
        mode="climate", city=dest,
        days=[DailyWeather(
            date="2026-05-15", temp_max=35.0, temp_min=23.0,
            precipitation_prob=None, precipitation_sum=8.5, weather_description="",
        )],
    )
    dr = DateRange.from_string(date_range_str)
    ks.update_weather(dest, dr, wo)
    return {
        "status": "ok",
        "summary": (
            f"{dest} {date_range_str} (historical avg): "
            f"avg high 35°C / low 23°C, ~8.5mm/day precip."
        ),
    }


def _itinerary_ok(destinations: list[str], ks: KnowledgeState) -> dict:
    """Update KS and return a response matching render_itinerary output."""
    days = [
        ItineraryDay(
            day_num=1, location=destinations[0], is_arrival=True,
            slots=[TimeSlot(
                start_time="15:00",
                activity=Activity(name="Check-in and orientation walk", tags=["outdoor"], indoor=False),
            )],
        ),
        ItineraryDay(
            day_num=2, location=destinations[0],
            slots=[TimeSlot(
                start_time="09:00",
                activity=Activity(name="Temple visit", tags=["cultural"], indoor=False, duration_min=120),
            )],
        ),
        ItineraryDay(
            day_num=3, location=destinations[0], is_departure=True,
            slots=[TimeSlot(
                start_time="09:00",
                activity=Activity(name="Morning market stroll", tags=["food"], indoor=False, duration_min=60),
            )],
        ),
    ]
    itinerary = Itinerary(destinations=destinations, start_date="2026-03-10", days=days)
    ks.update_itinerary(frozenset(destinations), itinerary)
    return {"status": "ok", "summary": render_itinerary(itinerary)}


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------

def _messages(orchestrator: Orchestrator) -> list[dict]:
    return orchestrator._agent._history.messages


def _get_tool_calls(messages: list[dict], tool_name: str) -> list[dict]:
    return [
        tc
        for msg in messages
        if msg.get("role") == "assistant" and msg.get("tool_calls")
        for tc in msg["tool_calls"]
        if tc["function"]["name"] == tool_name
    ]


def _get_specialist_calls(messages: list[dict]) -> list[tuple[str, dict]]:
    return [
        (tc["function"]["name"], tc)
        for msg in messages
        if msg.get("role") == "assistant" and msg.get("tool_calls")
        for tc in msg["tool_calls"]
        if tc["function"]["name"] in _SPECIALIST_TOOLS
    ]


def _parse_args(tc: dict) -> dict:
    return json.loads(tc["function"].get("arguments", "{}"))


def _first_msg_index(messages: list[dict], tool_name: str) -> int | None:
    for i, msg in enumerate(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            if any(tc["function"]["name"] == tool_name for tc in msg["tool_calls"]):
                return i
    return None


def _same_turn(messages: list[dict], tool_a: str, tool_b: str) -> bool:
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            names = {tc["function"]["name"] for tc in msg["tool_calls"]}
            if tool_a in names and tool_b in names:
                return True
    return False


def _call_before(messages: list[dict], first_tool: str, second_tool: str) -> bool:
    i = _first_msg_index(messages, first_tool)
    j = _first_msg_index(messages, second_tool)
    return i is not None and j is not None and i < j


# ---------------------------------------------------------------------------
# Artifact file cleanup
# ---------------------------------------------------------------------------

def _cleanup_artifact_files(messages: list[dict]) -> None:
    for msg in messages:
        if msg.get("role") == "tool":
            try:
                result = json.loads(msg.get("content", "{}"))
                summary = result.get("summary", "")
                if "Artifact saved to:" in summary:
                    file_path = summary.split("Artifact saved to:")[-1].strip()
                    Path(file_path).unlink(missing_ok=True)
            except (json.JSONDecodeError, OSError):
                pass


# ---------------------------------------------------------------------------
# Result serialization
# ---------------------------------------------------------------------------

def _serialize_turns(messages: list[dict]) -> list[list[dict]]:
    turns = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            turns.append([
                {"name": tc["function"]["name"], "args": _parse_args(tc)}
                for tc in msg["tool_calls"]
            ])
    return turns


# ---------------------------------------------------------------------------
# Run context + runner
# ---------------------------------------------------------------------------

class _Run:
    def __init__(self):
        self.orchestrator: Orchestrator | None = None
        self.response: str = ""
        self.extras: dict = {}


def run_test(fn, llm, search_client, serpapi_client, weather_client, currency_client) -> dict:
    name = fn.__name__
    run = _Run()
    try:
        fn(llm, search_client, serpapi_client, weather_client, currency_client, run)
        msgs = _messages(run.orchestrator) if run.orchestrator else []
        return {
            "name": name, "passed": True, "details": "",
            "turns": _serialize_turns(msgs), "response": run.response,
            **run.extras,
        }
    except AssertionError as e:
        msgs = _messages(run.orchestrator) if run.orchestrator else []
        return {
            "name": name, "passed": False, "details": str(e),
            "turns": _serialize_turns(msgs), "response": run.response,
            **run.extras,
        }
    except Exception as e:
        msgs = _messages(run.orchestrator) if run.orchestrator else []
        return {
            "name": name, "passed": False,
            "details": f"EXCEPTION: {type(e).__name__}: {e}",
            "turns": _serialize_turns(msgs), "response": run.response,
            **run.extras,
        }
    finally:
        if run.orchestrator:
            _cleanup_artifact_files(_messages(run.orchestrator))


# ---------------------------------------------------------------------------
# Section 1 — Query routing: specialist selection (A)
# ---------------------------------------------------------------------------

def routing_no_explorer_for_decided_destination(llm, sc, sa, wc, cc, run):
    """Explorer must not be called when destination is decided; research must be (A1)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("I want to plan a trip to Tokyo in June")
    msgs = _messages(run.orchestrator)

    explorer_calls = _get_tool_calls(msgs, "explorer")
    run.extras["explorer_calls"] = [_parse_args(tc) for tc in explorer_calls]
    assert not explorer_calls, "explorer called despite destination being decided (Tokyo)"

    research_calls = _get_tool_calls(msgs, "destination_research")
    run.extras["research_calls"] = [_parse_args(tc) for tc in research_calls]
    assert research_calls, "no destination_research call despite known destination"
    tokyo_call = any("tokyo" in _parse_args(tc).get("destination", "").lower() for tc in research_calls)
    assert tokyo_call, (
        f"destination_research not called for Tokyo. "
        f"Destinations: {[_parse_args(tc).get('destination') for tc in research_calls]}"
    )


def routing_explorer_for_undecided_destination(llm, sc, sa, wc, cc, run):
    """Explorer must be called for undecided destination; not in same turn as research (A2)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("I want a beach trip somewhere in South East Asia")
    msgs = _messages(run.orchestrator)

    explorer_calls = _get_tool_calls(msgs, "explorer")
    assert explorer_calls, "no explorer call — expected explorer for undecided destination"

    if _get_tool_calls(msgs, "destination_research"):
        assert not _same_turn(msgs, "explorer", "destination_research"), (
            "destination_research called in the same turn as explorer — "
            "research should wait until a destination is chosen"
        )


def routing_itinerary_requires_full_research_and_weather(llm, sc, sa, wc, cc, run):
    """Itinerary must follow full research and weather — both must be called first (A3)."""
    run.orchestrator = _make_orchestrator(
        llm, sc, sa, wc, cc, knowledge=_ks_with_light_research("Kyoto")
    )
    run.response = run.orchestrator.turn("Build me an itinerary for Kyoto next March")
    msgs = _messages(run.orchestrator)

    research_calls = _get_tool_calls(msgs, "destination_research")
    full_calls = [tc for tc in research_calls if _parse_args(tc).get("depth") == "full"]
    run.extras["research_calls"] = [_parse_args(tc) for tc in research_calls]
    assert full_calls, "no full-depth destination_research — expected escalation from light before itinerary"

    weather_calls = _get_tool_calls(msgs, "weather")
    run.extras["weather_calls"] = [_parse_args(tc) for tc in weather_calls]
    assert weather_calls, "no weather call — required before itinerary"

    itinerary_calls = _get_tool_calls(msgs, "itinerary_planner")
    if itinerary_calls:
        full_pos = next(
            i for i, msg in enumerate(msgs)
            if msg.get("role") == "assistant" and msg.get("tool_calls")
            and any(tc["function"]["name"] == "destination_research"
                    and _parse_args(tc).get("depth") == "full"
                    for tc in msg["tool_calls"])
        )
        weather_pos = _first_msg_index(msgs, "weather")
        itin_pos = _first_msg_index(msgs, "itinerary_planner")
        assert full_pos < itin_pos, f"itinerary called before full research"
        assert weather_pos < itin_pos, f"itinerary called before weather"


def routing_itinerary_requires_weather(llm, sc, sa, wc, cc, run):
    """Itinerary must not precede weather even when research is already in state (A4)."""
    run.orchestrator = _make_orchestrator(
        llm, sc, sa, wc, cc, knowledge=_ks_with_full_research("Bali", country="Indonesia")
    )
    run.response = run.orchestrator.turn("Plan my Bali itinerary for August")
    msgs = _messages(run.orchestrator)

    weather_calls = _get_tool_calls(msgs, "weather")
    run.extras["weather_calls"] = [_parse_args(tc) for tc in weather_calls]
    assert weather_calls, "no weather call — required before itinerary even when research is in state"

    itinerary_calls = _get_tool_calls(msgs, "itinerary_planner")
    if itinerary_calls:
        weather_pos = _first_msg_index(msgs, "weather")
        itin_pos = _first_msg_index(msgs, "itinerary_planner")
        assert weather_pos < itin_pos, "itinerary called before weather"


def routing_budget_after_research_and_transport(llm, sc, sa, wc, cc, run):
    """Budget must not appear before research and transportation are both complete (A5)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("What's the budget for a trip from London to Bangkok?")
    msgs = _messages(run.orchestrator)

    run.extras["tool_order"] = [
        tc["function"]["name"]
        for msg in msgs if msg.get("role") == "assistant" and msg.get("tool_calls")
        for tc in msg["tool_calls"]
    ]
    budget_calls = _get_tool_calls(msgs, "budget")
    if budget_calls:
        research_calls = _get_tool_calls(msgs, "destination_research")
        transport_calls = _get_tool_calls(msgs, "transportation")
        assert research_calls, "budget called but destination_research was never called"
        assert transport_calls, "budget called but transportation was never called"
        assert _call_before(msgs, "destination_research", "budget"), "budget before destination_research"
        assert _call_before(msgs, "transportation", "budget"), "budget before transportation"


def routing_no_artifact_without_explicit_request(llm, sc, sa, wc, cc, run):
    """Artifact must not be called for an overview request; research must be light depth (A6)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("Tell me about Lisbon")
    msgs = _messages(run.orchestrator)

    artifact_calls = _get_tool_calls(msgs, "artifact")
    run.extras["artifact_calls"] = len(artifact_calls)
    assert not artifact_calls, "artifact called speculatively for a general overview request"

    research_calls = _get_tool_calls(msgs, "destination_research")
    run.extras["research_calls"] = [_parse_args(tc) for tc in research_calls]
    light_calls = [tc for tc in research_calls if _parse_args(tc).get("depth") == "light"]
    full_calls = [tc for tc in research_calls if _parse_args(tc).get("depth") == "full"]
    assert light_calls, "no light-depth research for a simple overview request"
    assert not full_calls, "full-depth research for a simple overview — premature escalation"


def routing_light_depth_for_overview(llm, sc, sa, wc, cc, run):
    """Full depth must not be used when only a vague overview is requested (A7)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("What's Bali like?")
    msgs = _messages(run.orchestrator)

    research_calls = _get_tool_calls(msgs, "destination_research")
    run.extras["research_calls"] = [_parse_args(tc) for tc in research_calls]
    light_calls = [tc for tc in research_calls if _parse_args(tc).get("depth") == "light"]
    full_calls = [tc for tc in research_calls if _parse_args(tc).get("depth") == "full"]
    assert light_calls, "no light-depth research for a general overview question"
    assert not full_calls, "full-depth research called prematurely — no itinerary or artifact requested"


def routing_full_escalation_from_light_before_itinerary(llm, sc, sa, wc, cc, run):
    """When light research is in state and itinerary is requested, escalate directly to full (A8)."""
    run.orchestrator = _make_orchestrator(
        llm, sc, sa, wc, cc, knowledge=_ks_with_light_research("Tokyo")
    )
    run.response = run.orchestrator.turn("Plan a 5-day Tokyo itinerary for September")
    msgs = _messages(run.orchestrator)

    research_calls = _get_tool_calls(msgs, "destination_research")
    run.extras["research_calls"] = [_parse_args(tc) for tc in research_calls]
    full_calls = [tc for tc in research_calls if _parse_args(tc).get("depth") == "full"]
    light_calls = [tc for tc in research_calls if _parse_args(tc).get("depth") == "light"]
    assert full_calls, "no full-depth research — expected escalation since itinerary requested"
    assert not light_calls, (
        "light-depth research re-called when light already in state — "
        "should escalate directly to full"
    )


# ---------------------------------------------------------------------------
# Section 1 — Query routing: KnowledgeState reuse (B)
# ---------------------------------------------------------------------------

def routing_no_research_when_full_in_state(llm, sc, sa, wc, cc, run):
    """Research must not be re-called when full depth and weather are already in state (B1)."""
    run.orchestrator = _make_orchestrator(
        llm, sc, sa, wc, cc,
        knowledge=_ks_with_full_research_and_weather("Paris", country="France"),
    )
    run.response = run.orchestrator.turn("Can you plan a Paris itinerary?")
    msgs = _messages(run.orchestrator)

    research_calls = _get_tool_calls(msgs, "destination_research")
    run.extras["research_calls"] = [_parse_args(tc) for tc in research_calls]
    assert not research_calls, (
        "destination_research called when full research already in KnowledgeState — redundant"
    )
    itinerary_calls = _get_tool_calls(msgs, "itinerary_planner")
    assert itinerary_calls, "itinerary_planner not called despite full research and weather in state"


def routing_no_weather_when_in_state(llm, sc, sa, wc, cc, run):
    """Weather must not be re-fetched when already present for the same destination (B2)."""
    run.orchestrator = _make_orchestrator(
        llm, sc, sa, wc, cc,
        knowledge=_ks_with_full_research_and_weather("Tokyo"),
    )
    run.response = run.orchestrator.turn("What activities should I plan for Tokyo given the weather?")
    msgs = _messages(run.orchestrator)

    weather_calls = _get_tool_calls(msgs, "weather")
    run.extras["weather_calls"] = [_parse_args(tc) for tc in weather_calls]
    assert not weather_calls, (
        "weather called when Tokyo weather already in KnowledgeState — redundant call"
    )


# ---------------------------------------------------------------------------
# Section 1 — Query routing: parallelisation (C)
# ---------------------------------------------------------------------------

def routing_research_weather_transport_parallel(llm, sc, sa, wc, cc, run):
    """Research, weather, and transport must appear in the same turn when all are needed (C1)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("I'm flying from Singapore to Bali next July for 7 days")
    msgs = _messages(run.orchestrator)

    _THREE = {"destination_research", "weather", "transportation"}
    all_three_parallel = any(
        _THREE.issubset({tc["function"]["name"] for tc in msg["tool_calls"]})
        for msg in msgs if msg.get("role") == "assistant" and msg.get("tool_calls")
    )
    at_least_two_parallel = any(
        sum(1 for tc in msg["tool_calls"] if tc["function"]["name"] in _THREE) >= 2
        for msg in msgs if msg.get("role") == "assistant" and msg.get("tool_calls")
    )
    run.extras["all_three_parallel"] = all_three_parallel
    run.extras["tool_turns"] = _serialize_turns(msgs)
    assert at_least_two_parallel, (
        "research, weather, and transportation appear serialised — "
        "at least 2 of the 3 should be in the same turn"
    )


def routing_multi_destination_weather_parallel(llm, sc, sa, wc, cc, run):
    """Weather for multiple destinations must be issued in a single parallel turn (C2)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("Get me weather for Tokyo and Kyoto in October")
    msgs = _messages(run.orchestrator)

    parallel_weather = any(
        sum(1 for tc in msg["tool_calls"] if tc["function"]["name"] == "weather") >= 2
        for msg in msgs if msg.get("role") == "assistant" and msg.get("tool_calls")
    )
    all_weather_dests = [
        _parse_args(tc).get("destination", "") for tc in _get_tool_calls(msgs, "weather")
    ]
    run.extras["weather_destinations"] = all_weather_dests
    assert parallel_weather, (
        f"weather for Tokyo and Kyoto serialised — expected in the same turn. "
        f"Destinations called: {all_weather_dests}"
    )


def routing_two_research_not_in_same_turn(llm, sc, sa, wc, cc, run):
    """Two destination_research calls must be sequential, never in the same turn (C3)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("Compare Tokyo and Seoul for a 2-week trip")
    msgs = _messages(run.orchestrator)

    same_turn_research = any(
        sum(1 for tc in msg["tool_calls"] if tc["function"]["name"] == "destination_research") >= 2
        for msg in msgs if msg.get("role") == "assistant" and msg.get("tool_calls")
    )
    run.extras["tool_turns"] = _serialize_turns(msgs)
    assert not same_turn_research, (
        "two destination_research calls in the same turn — must be sequential (one per turn)"
    )


def routing_budget_not_parallel_with_prerequisites(llm, sc, sa, wc, cc, run):
    """Budget must not appear in the same turn as research or transportation (C4)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("Plan a full trip from London to Tokyo in May, including costs")
    msgs = _messages(run.orchestrator)

    budget_with_prereqs = any(
        any(tc["function"]["name"] == "budget" for tc in msg["tool_calls"])
        and any(tc["function"]["name"] in {"destination_research", "transportation"}
                for tc in msg["tool_calls"])
        for msg in msgs if msg.get("role") == "assistant" and msg.get("tool_calls")
    )
    run.extras["tool_turns"] = _serialize_turns(msgs)
    assert not budget_with_prereqs, (
        "budget called in the same turn as destination_research or transportation — "
        "budget must follow its prerequisites"
    )


# ---------------------------------------------------------------------------
# Section 2 — Specialist argument quality + error handling: Explorer
# ---------------------------------------------------------------------------

def explorer_no_retry_on_hard_failure(llm, sc, sa, wc, cc, run):
    """On a hard explorer failure, no further specialist calls must appear (E4)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    _patch(run.orchestrator, "explorer",
           {"status": "error", "summary": "ExplorerSpecialist failed: API key invalid"})
    run.response = run.orchestrator.turn("Find me a beach destination in South East Asia")
    msgs = _messages(run.orchestrator)

    explorer_calls = _get_tool_calls(msgs, "explorer")
    assert explorer_calls, "no explorer call found"

    explorer_pos = _first_msg_index(msgs, "explorer")
    post_failure = [
        tc["function"]["name"]
        for msg in msgs[explorer_pos + 1:]
        if msg.get("role") == "assistant" and msg.get("tool_calls")
        for tc in msg["tool_calls"]
        if tc["function"]["name"] in _SPECIALIST_TOOLS
    ]
    run.extras["post_failure_calls"] = post_failure
    assert not post_failure, f"specialist calls after hard explorer failure: {post_failure}"


def explorer_no_research_after_zero_candidates(llm, sc, sa, wc, cc, run):
    """When explorer returns 0 candidates, destination_research must not be called (E5)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    _patch(run.orchestrator, "explorer", {"status": "ok", "summary": "Found 0 candidates:"})
    run.response = run.orchestrator.turn("Find me a beach destination")
    msgs = _messages(run.orchestrator)

    research_calls = _get_tool_calls(msgs, "destination_research")
    run.extras["research_calls"] = [_parse_args(tc) for tc in research_calls]
    assert not research_calls, (
        "destination_research called after explorer returned 0 candidates — no destination to research"
    )


def explorer_query_strips_negations(llm, sc, sa, wc, cc, run):
    """Explorer query must contain positive signals and no negation words (E1)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn(
        "I want a nature trip in South East Asia, not too heavy on nightlife"
    )
    msgs = _messages(run.orchestrator)

    explorer_calls = _get_tool_calls(msgs, "explorer")
    assert explorer_calls, "no explorer call found"
    query = _parse_args(explorer_calls[0]).get("query", "")
    run.extras["explorer_query"] = query

    negation_found = any(neg in query.lower() for neg in ["not", "avoid", "nightlife", "no "])
    assert not negation_found, f"negation found in explorer query: '{query}'"
    has_positive = any(sig in query.lower() for sig in ["south east asia", "southeast asia", "nature", "sea"])
    assert has_positive, f"positive signals missing from explorer query: '{query}'"


# ---------------------------------------------------------------------------
# Section 2 — Specialist argument quality: Weather
# ---------------------------------------------------------------------------

def weather_city_level_not_region_for_sikkim(llm, sc, sa, wc, cc, run):
    """Weather must use a specific city (Gangtok), not the region name (Sikkim) (W1)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("I want to plan a trip to Sikkim in April and need weather info")
    msgs = _messages(run.orchestrator)

    weather_calls = _get_tool_calls(msgs, "weather")
    destinations = [_parse_args(tc).get("destination", "") for tc in weather_calls]
    run.extras["weather_destinations"] = destinations

    sikkim_calls = [d for d in destinations if d.lower().strip() == "sikkim"]
    assert not sikkim_calls, (
        f"weather called with 'Sikkim' — must use a specific city like Gangtok. "
        f"Destinations tried: {destinations}"
    )
    has_gangtok = any("gangtok" in d.lower() for d in destinations)
    assert has_gangtok, (
        f"no weather call for Gangtok despite Sikkim being a region with Gangtok as capital. "
        f"Destinations tried: {destinations}"
    )


def weather_specific_date_range_when_dates_known(llm, sc, sa, wc, cc, run):
    """When user provides exact dates, date_range must be specific not month-only (W2)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("Plan my trip to Bali from June 20 to June 30 2026")
    msgs = _messages(run.orchestrator)

    weather_calls = _get_tool_calls(msgs, "weather")
    date_ranges = [_parse_args(tc).get("date_range", "") for tc in weather_calls]
    run.extras["weather_date_ranges"] = date_ranges

    assert weather_calls, "no weather call"
    specific = any(
        "2026-06-20" in dr or "june 20" in dr.lower() or "20 june" in dr.lower()
        for dr in date_ranges
    )
    assert specific, (
        f"no weather call with specific date range — month-only range used when exact dates were given. "
        f"Date ranges: {date_ranges}"
    )


def weather_called_for_all_cities_multi_destination(llm, sc, sa, wc, cc, run):
    """Weather must be called separately for every city in a multi-city trip (W3)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("I'm visiting Tokyo and Kyoto in October for 2 weeks")
    msgs = _messages(run.orchestrator)

    weather_calls = _get_tool_calls(msgs, "weather")
    destinations = [_parse_args(tc).get("destination", "").lower() for tc in weather_calls]
    run.extras["weather_destinations"] = destinations

    has_tokyo = any("tokyo" in d for d in destinations)
    has_kyoto = any("kyoto" in d for d in destinations)
    assert has_tokyo, f"weather not called for Tokyo. Destinations: {destinations}"
    assert has_kyoto, f"weather not called for Kyoto. Destinations: {destinations}"


# ---------------------------------------------------------------------------
# Section 2 — Specialist argument quality + error handling: Weather
# ---------------------------------------------------------------------------

def weather_retry_uses_different_string_after_geocode_failure(llm, sc, sa, wc, cc, run):
    """After a geocode failure, the retry must use a different destination string (W4)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    ks = run.orchestrator._knowledge
    first_call_done = [False]

    def weather_execute(**kwargs):
        dest = kwargs.get("destination", "")
        date_range_str = kwargs.get("date_range", "May 2026")
        if not first_call_done[0]:
            first_call_done[0] = True
            return {"status": "error", "summary": f"WeatherSpecialist failed: could not geocode '{dest}'"}
        return _weather_ok(dest, date_range_str, ks)

    _patch(run.orchestrator, "weather", weather_execute)
    run.response = run.orchestrator.turn("Get the weather for Pai, Thailand in May")
    msgs = _messages(run.orchestrator)

    weather_calls = _get_tool_calls(msgs, "weather")
    destinations = [_parse_args(tc).get("destination", "") for tc in weather_calls]
    run.extras["weather_destinations"] = destinations

    if len(weather_calls) >= 2:
        first_dest = destinations[0]
        second_dest = destinations[1]
        assert first_dest.lower() != second_dest.lower(), (
            f"retry used identical destination string '{second_dest}' — "
            f"must use a different string after geocode failure"
        )


def weather_failure_does_not_block_other_city(llm, sc, sa, wc, cc, run):
    """A weather geocode failure for one city must not block weather for other cities (W5)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    ks = run.orchestrator._knowledge

    def weather_execute(**kwargs):
        dest = kwargs.get("destination", "")
        date_range_str = kwargs.get("date_range", "May 2026")
        if "pai" in dest.lower():
            return {"status": "error", "summary": f"WeatherSpecialist failed: could not geocode '{dest}'"}
        return _weather_ok(dest, date_range_str, ks)

    _patch(run.orchestrator, "weather", weather_execute)
    run.response = run.orchestrator.turn(
        "Plan a Chiang Mai and Pai trip in May for 10 days — need weather for both"
    )
    msgs = _messages(run.orchestrator)

    weather_calls = _get_tool_calls(msgs, "weather")
    destinations = [_parse_args(tc).get("destination", "").lower() for tc in weather_calls]
    run.extras["weather_destinations"] = destinations

    has_chiang_mai = any("chiang mai" in d for d in destinations)
    assert has_chiang_mai, (
        f"weather not called for Chiang Mai despite Pai failure — "
        f"one city's failure must not block others. Destinations: {destinations}"
    )


# ---------------------------------------------------------------------------
# Section 2 — Specialist argument quality + error handling: DestinationResearch
# ---------------------------------------------------------------------------

def research_at_region_level_not_sub_city(llm, sc, sa, wc, cc, run):
    """Research destination must be the region entity ('Sikkim'), not a sub-city (R1)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("I want to plan a trip to Sikkim in April")
    msgs = _messages(run.orchestrator)

    research_calls = _get_tool_calls(msgs, "destination_research")
    destinations = [_parse_args(tc).get("destination", "") for tc in research_calls]
    run.extras["research_destinations"] = destinations

    assert research_calls, "no destination_research call"
    has_sikkim = any("sikkim" in d.lower() for d in destinations)
    has_gangtok = any("gangtok" in d.lower() for d in destinations)
    assert has_sikkim, f"destination_research not called with 'Sikkim'. Got: {destinations}"
    assert not has_gangtok, (
        f"destination_research called with 'Gangtok' (sub-city) instead of 'Sikkim'. Got: {destinations}"
    )


def research_failure_blocks_itinerary_and_budget(llm, sc, sa, wc, cc, run):
    """After a research hard failure, itinerary and budget must not be called (R3)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    _patch(run.orchestrator, "destination_research",
           {"status": "error", "summary": "DestinationResearchSpecialist failed: API key invalid"})
    run.response = run.orchestrator.turn("Plan a full trip to Tokyo with itinerary and budget")
    msgs = _messages(run.orchestrator)

    itinerary_calls = _get_tool_calls(msgs, "itinerary_planner")
    budget_calls = _get_tool_calls(msgs, "budget")
    run.extras["post_failure_specialist_calls"] = [
        tc["function"]["name"]
        for msg in msgs if msg.get("role") == "assistant" and msg.get("tool_calls")
        for tc in msg["tool_calls"] if tc["function"]["name"] in _SPECIALIST_TOOLS
    ]
    assert not itinerary_calls, "itinerary_planner called after research hard failure"
    assert not budget_calls, "budget called after research hard failure"


# ---------------------------------------------------------------------------
# Section 2 — Specialist argument quality: Transportation
# ---------------------------------------------------------------------------

def transport_round_trip_for_simple_return(llm, sc, sa, wc, cc, run):
    """Simple A→B→A must use trip_type='round_trip' with no separate reverse leg (T1)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("I'm flying from Mumbai to Tokyo and back, 2 weeks in June")
    msgs = _messages(run.orchestrator)

    transport_calls = _get_tool_calls(msgs, "transportation")
    run.extras["transport_calls"] = [_parse_args(tc) for tc in transport_calls]

    assert transport_calls, "no transportation call"
    round_trip_calls = [tc for tc in transport_calls if _parse_args(tc).get("trip_type") == "round_trip"]
    assert round_trip_calls, f"no round_trip call for simple A→B→A. Calls: {run.extras['transport_calls']}"

    reverse_calls = [
        tc for tc in transport_calls
        if "tokyo" in _parse_args(tc).get("origin", "").lower()
        and "mumbai" in _parse_args(tc).get("destination", "").lower()
    ]
    assert not reverse_calls, (
        f"separate reverse leg (Tokyo→Mumbai) looked up for what should be a round_trip"
    )


def transport_one_way_for_each_multi_city_leg(llm, sc, sa, wc, cc, run):
    """Every leg of a multi-city itinerary must use trip_type='one_way' (T2)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn(
        "Fly London to Tokyo, then Tokyo to Bangkok, then Bangkok back to London"
    )
    msgs = _messages(run.orchestrator)

    transport_calls = _get_tool_calls(msgs, "transportation")
    run.extras["transport_calls"] = [_parse_args(tc) for tc in transport_calls]

    round_trip_calls = [tc for tc in transport_calls if _parse_args(tc).get("trip_type") == "round_trip"]
    assert not round_trip_calls, (
        f"round_trip used for a multi-city leg: {[_parse_args(tc) for tc in round_trip_calls]}"
    )
    london_tokyo = any(
        "london" in _parse_args(tc).get("origin", "").lower()
        and "tokyo" in _parse_args(tc).get("destination", "").lower()
        for tc in transport_calls
    )
    assert london_tokyo, f"no London→Tokyo transport call. Calls: {run.extras['transport_calls']}"


def transport_no_reverse_when_outbound_is_ground_only(llm, sc, sa, wc, cc, run):
    """When outbound route is ground-only, reverse leg must not be looked up separately (T4)."""
    run.orchestrator = _make_orchestrator(
        llm, sc, sa, wc, cc, knowledge=_ks_with_ground_route("Chiang Mai", "Pai")
    )
    run.response = run.orchestrator.turn("How do I get from Pai back to Chiang Mai?")
    msgs = _messages(run.orchestrator)

    transport_calls = _get_tool_calls(msgs, "transportation")
    run.extras["transport_calls"] = [_parse_args(tc) for tc in transport_calls]

    reverse_calls = [
        tc for tc in transport_calls
        if "pai" in _parse_args(tc).get("origin", "").lower()
        and "chiang mai" in _parse_args(tc).get("destination", "").lower()
    ]
    assert not reverse_calls, (
        f"reverse ground leg (Pai→Chiang Mai) looked up separately — "
        f"ground options are symmetric and already in KnowledgeState"
    )


# ---------------------------------------------------------------------------
# Section 2 — Specialist argument quality: ItineraryPlanner
# ---------------------------------------------------------------------------

def itinerary_destinations_in_travel_order(llm, sc, sa, wc, cc, run):
    """Destinations list must reflect the travel order stated by the user (IP1)."""
    ks = _ks_with_full_research("Tokyo")
    ks.update_research("Kyoto", DestinationResearch(
        name="Kyoto", country="Japan", depth="full",
        vibe="Ancient imperial capital.", top_attractions=["Fushimi Inari", "Kinkaku-ji"],
        summary="Kyoto is Japan's cultural heart.",
        safety_summary=StringWithAttribution(text="Safe.", source_url=None),
        festivals=["Gion Matsuri (July)"],
    ))
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc, knowledge=ks)
    run.response = run.orchestrator.turn(
        "I'm flying into Tokyo, spending 7 days there, then 3 days in Kyoto before flying home"
    )
    msgs = _messages(run.orchestrator)

    itinerary_calls = _get_tool_calls(msgs, "itinerary_planner")
    assert itinerary_calls, "no itinerary_planner call"
    destinations = _parse_args(itinerary_calls[0]).get("destinations", [])
    run.extras["destinations"] = destinations

    tokyo_idx = next((i for i, d in enumerate(destinations) if "tokyo" in d.lower()), None)
    kyoto_idx = next((i for i, d in enumerate(destinations) if "kyoto" in d.lower()), None)
    assert tokyo_idx is not None, f"Tokyo absent from destinations: {destinations}"
    assert kyoto_idx is not None, f"Kyoto absent from destinations: {destinations}"
    assert tokyo_idx < kyoto_idx, f"Tokyo must appear before Kyoto. Got: {destinations}"


def itinerary_missing_research_triggers_escalation_and_reinvocation(llm, sc, sa, wc, cc, run):
    """Missing-research error must trigger full research escalation then itinerary re-invocation (IP5)."""
    run.orchestrator = _make_orchestrator(
        llm, sc, sa, wc, cc, knowledge=_ks_with_light_research("Kyoto")
    )
    ks = run.orchestrator._knowledge
    itinerary_seq = _Sequence(
        {
            "status": "error",
            "summary": (
                "ItineraryPlannerSpecialist requires full-depth research for all destinations. "
                "Missing or incomplete: Kyoto. "
                "Call DestinationResearchSpecialist with depth='full' for each first."
            ),
        },
        lambda **kwargs: _itinerary_ok(kwargs.get("destinations", ["Kyoto"]), ks),
    )
    _patch(run.orchestrator, "itinerary_planner", itinerary_seq)
    run.response = run.orchestrator.turn("Build a full itinerary for Kyoto in March")
    msgs = _messages(run.orchestrator)

    research_calls = _get_tool_calls(msgs, "destination_research")
    full_calls = [tc for tc in research_calls if _parse_args(tc).get("depth") == "full"]
    run.extras["research_calls"] = [_parse_args(tc) for tc in research_calls]
    assert full_calls, (
        "full destination_research not called after itinerary error — expected escalation to fill the gap"
    )

    itinerary_positions = [
        i for i, msg in enumerate(msgs)
        if msg.get("role") == "assistant" and msg.get("tool_calls")
        and any(tc["function"]["name"] == "itinerary_planner" for tc in msg["tool_calls"])
    ]
    run.extras["itinerary_call_count"] = len(itinerary_positions)
    assert len(itinerary_positions) >= 2, (
        f"itinerary_planner called only {len(itinerary_positions)} time(s) — "
        "expected re-invocation after filling the research gap"
    )

    full_research_pos = next(
        (i for i, msg in enumerate(msgs)
         if msg.get("role") == "assistant" and msg.get("tool_calls")
         and any(tc["function"]["name"] == "destination_research"
                 and _parse_args(tc).get("depth") == "full"
                 for tc in msg["tool_calls"])),
        None,
    )
    if full_research_pos is not None and len(itinerary_positions) >= 2:
        assert full_research_pos < itinerary_positions[-1], (
            "second itinerary_planner call appears before full research"
        )


# ---------------------------------------------------------------------------
# Section 2 — Specialist argument quality + error handling: Artifact
# ---------------------------------------------------------------------------

def artifact_query_preserves_requirements(llm, sc, sa, wc, cc, run):
    """Artifact query must carry all document section requirements stated by the user (AR1)."""
    ks = _ks_with_full_research_and_weather("Tokyo")
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc, knowledge=ks)
    run.response = run.orchestrator.turn(
        "Generate a full travel document for my Tokyo trip "
        "with budget breakdown and day-by-day itinerary"
    )
    msgs = _messages(run.orchestrator)

    artifact_calls = _get_tool_calls(msgs, "artifact")
    assert artifact_calls, "no artifact call"
    query = _parse_args(artifact_calls[0]).get("query", "")
    run.extras["artifact_query"] = query

    has_budget = any(kw in query.lower() for kw in ["budget", "cost", "costs", "breakdown"])
    has_itinerary = any(kw in query.lower() for kw in ["itinerary", "day-by-day", "schedule", "daily"])
    assert has_budget, f"budget requirement dropped from artifact query: '{query}'"
    assert has_itinerary, f"itinerary requirement dropped from artifact query: '{query}'"


def artifact_needs_data_gaps_resolved_before_reinvocation(llm, sc, sa, wc, cc, run):
    """After needs_data, all listed gaps must be filled before artifact is re-invoked (AR2)."""
    artifact_seq = _Sequence(
        {
            "status": "needs_data",
            "summary": (
                "Cannot generate artifact — missing required data:\n"
                "- full-depth research for Kyoto\n"
                "- day-by-day itinerary for Kyoto\n"
                "Gather this data first, then call artifact again."
            ),
        },
        {"status": "ok", "summary": "Artifact saved to: /tmp/kyoto_trip.md"},
    )
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    _patch(run.orchestrator, "artifact", artifact_seq)
    run.response = run.orchestrator.turn("Save my Kyoto trip plan to a document")
    msgs = _messages(run.orchestrator)

    artifact_positions = [
        i for i, msg in enumerate(msgs)
        if msg.get("role") == "assistant" and msg.get("tool_calls")
        and any(tc["function"]["name"] == "artifact" for tc in msg["tool_calls"])
    ]
    run.extras["artifact_call_count"] = len(artifact_positions)
    assert len(artifact_positions) >= 2, (
        f"artifact not re-invoked after needs_data — called {len(artifact_positions)} time(s)"
    )

    full_research_calls = [
        tc for tc in _get_tool_calls(msgs, "destination_research")
        if _parse_args(tc).get("depth") == "full"
    ]
    itinerary_calls = _get_tool_calls(msgs, "itinerary_planner")
    run.extras["full_research_count"] = len(full_research_calls)
    run.extras["itinerary_count"] = len(itinerary_calls)
    assert full_research_calls, "full research not called to resolve needs_data gap"
    assert itinerary_calls, "itinerary_planner not called to resolve needs_data gap"

    if len(artifact_positions) >= 2:
        first_artifact = artifact_positions[0]
        second_artifact = artifact_positions[1]
        gap_fill_positions = [
            i for i, msg in enumerate(msgs)
            if msg.get("role") == "assistant" and msg.get("tool_calls")
            and any(tc["function"]["name"] in {"destination_research", "itinerary_planner"}
                    for tc in msg["tool_calls"])
        ]
        gap_filled_between = any(first_artifact < pos < second_artifact for pos in gap_fill_positions)
        assert gap_filled_between, (
            "artifact re-invoked without any gap-filling calls between first and second invocation"
        )


# ---------------------------------------------------------------------------
# Section 3 — Clarification behaviour
# ---------------------------------------------------------------------------

def clarification_not_asked_when_all_info_present(llm, sc, sa, wc, cc, run):
    """When destination, dates, duration, and origin are all given, proceed immediately (CL1)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn(
        "I want to go to Tokyo in June for 7 days, flying from London"
    )
    msgs = _messages(run.orchestrator)

    specialist_calls = _get_specialist_calls(msgs)
    run.extras["specialist_calls"] = [name for name, _ in specialist_calls]
    assert specialist_calls, (
        "no specialist tool calls despite all blocking info present "
        "(destination, dates, duration, origin) — should not ask for clarification"
    )


def clarification_no_calls_when_intent_too_sparse(llm, sc, sa, wc, cc, run):
    """No specialist calls when intent is 'plan a trip' with no region or activity (CL2)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("I want to plan a trip")
    msgs = _messages(run.orchestrator)

    specialist_calls = _get_specialist_calls(msgs)
    run.extras["specialist_calls"] = [name for name, _ in specialist_calls]
    assert not specialist_calls, (
        f"specialist calls made without enough context: {run.extras['specialist_calls']}"
    )


def clarification_passport_not_asked_for_general_research(llm, sc, sa, wc, cc, run):
    """Passport must not be asked for a general research request (CL6)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("Tell me about Japan")
    msgs = _messages(run.orchestrator)

    passport_asked = "passport" in run.response.lower() or "nationality" in run.response.lower()
    run.extras["response_asks_passport"] = passport_asked
    assert not passport_asked, (
        "orchestrator asked about passport for a general research request — "
        "only needed for explicit visa queries"
    )
    research_calls = _get_tool_calls(msgs, "destination_research")
    assert research_calls, "destination_research not called for 'Tell me about Japan'"


def clarification_budget_tier_not_blocking(llm, sc, sa, wc, cc, run):
    """Budget tier must never be asked — orchestrator must proceed without it (CL7)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn(
        "I want to visit Bali in August for 10 days flying from Sydney"
    )
    msgs = _messages(run.orchestrator)

    specialist_calls = _get_specialist_calls(msgs)
    run.extras["specialist_calls"] = [name for name, _ in specialist_calls]
    assert specialist_calls, (
        "no specialist calls — should proceed without asking about budget tier"
    )


def clarification_dates_refused_research_proceeds_weather_skipped(llm, sc, sa, wc, cc, run):
    """When user refuses dates, research proceeds but weather and transport are skipped (CL12)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.orchestrator.turn("Plan a trip to Kyoto")
    run.response = run.orchestrator.turn("I don't have dates yet, just start planning")
    msgs = _messages(run.orchestrator)

    research_calls = _get_tool_calls(msgs, "destination_research")
    weather_calls = _get_tool_calls(msgs, "weather")
    transport_calls = _get_tool_calls(msgs, "transportation")
    run.extras["research_called"] = bool(research_calls)
    run.extras["weather_called"] = bool(weather_calls)
    run.extras["transport_called"] = bool(transport_calls)

    assert research_calls, "destination_research not called — should proceed with research despite no dates"
    assert not weather_calls, "weather called despite no dates given"
    assert not transport_calls, "transportation called despite no dates or origin city"


def clarification_origin_refused_transport_skipped(llm, sc, sa, wc, cc, run):
    """When user refuses origin city, only transport is skipped — research and weather proceed (CL13)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.orchestrator.turn("Plan a trip to Bangkok in October for 10 days")
    run.response = run.orchestrator.turn("Don't worry about flights for now, just start planning")
    msgs = _messages(run.orchestrator)

    research_calls = _get_tool_calls(msgs, "destination_research")
    weather_calls = _get_tool_calls(msgs, "weather")
    transport_calls = _get_tool_calls(msgs, "transportation")
    run.extras["research_called"] = bool(research_calls)
    run.extras["weather_called"] = bool(weather_calls)
    run.extras["transport_called"] = bool(transport_calls)

    assert research_calls, "destination_research not called — only transport should be skipped"
    assert weather_calls, "weather not called — only transport should be skipped"
    assert not transport_calls, "transportation called despite user refusing to provide origin city"


# ---------------------------------------------------------------------------
# Section 4 — update_user_context accuracy
# ---------------------------------------------------------------------------

def uc_called_when_trip_info_provided(llm, sc, sa, wc, cc, run):
    """update_user_context must be called when user provides trip info (UC1)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn(
        "I want to go to Tokyo in June for 7 days, solo, prefer cultural experiences"
    )
    msgs = _messages(run.orchestrator)

    uc_calls = _get_tool_calls(msgs, "update_user_context")
    run.extras["uc_calls"] = [_parse_args(tc) for tc in uc_calls]
    assert uc_calls, "update_user_context not called despite destination, dates, and preferences provided"


def uc_not_called_for_greetings(llm, sc, sa, wc, cc, run):
    """update_user_context must not be called for a greeting (UC2)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("Hi!")
    msgs = _messages(run.orchestrator)

    uc_calls = _get_tool_calls(msgs, "update_user_context")
    run.extras["uc_calls"] = [_parse_args(tc) for tc in uc_calls]
    assert not uc_calls, "update_user_context called for a greeting — not warranted"


def uc_precedes_specialist_tools(llm, sc, sa, wc, cc, run):
    """update_user_context must appear before any specialist tool in the same turn (UC5)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn(
        "I want to visit Bali in August for 10 days flying from Sydney"
    )
    msgs = _messages(run.orchestrator)

    uc_pos = _first_msg_index(msgs, "update_user_context")
    run.extras["uc_position"] = uc_pos

    if uc_pos is not None:
        for tool_name in ("destination_research", "weather", "transportation", "budget", "itinerary_planner"):
            specialist_pos = _first_msg_index(msgs, tool_name)
            if specialist_pos is not None:
                assert uc_pos <= specialist_pos, (
                    f"update_user_context (msg {uc_pos}) appears after {tool_name} (msg {specialist_pos})"
                )


def uc_accumulates_intent_across_turns(llm, sc, sa, wc, cc, run):
    """update_user_context in turn 2 must include all info from both turns (UC6)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.orchestrator.turn("I want to go to Tokyo, not interested in nightlife")
    n_after_turn1 = len(_messages(run.orchestrator))
    run.response = run.orchestrator.turn("7 days in June, flying from London")
    all_msgs = _messages(run.orchestrator)
    turn2_msgs = all_msgs[n_after_turn1:]

    uc_calls_t2 = _get_tool_calls(turn2_msgs, "update_user_context")
    if not uc_calls_t2:
        uc_calls_t2 = _get_tool_calls(all_msgs, "update_user_context")

    assert uc_calls_t2, "update_user_context not called in turn 2 with updated trip info"
    context = _parse_args(uc_calls_t2[-1]).get("context", "")
    run.extras["turn2_context"] = context

    assert "tokyo" in context.lower(), f"turn 2 context lost destination 'Tokyo': '{context}'"
    nightlife_mentioned = "nightlife" in context.lower()
    assert nightlife_mentioned, f"nightlife constraint absent from turn 2 context: '{context}'"
    has_june_or_london = "june" in context.lower() or "london" in context.lower()
    assert has_june_or_london, f"turn 2 context missing June/London: '{context}'"


# ---------------------------------------------------------------------------
# Section 5 — User-facing response quality
# ---------------------------------------------------------------------------

def response_no_raw_json(llm, sc, sa, wc, cc, run):
    """Response text must not contain raw tool output patterns (RS1)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("Tell me about Tokyo for a 7-day trip in June")

    leak_patterns = ['"status": "ok"', '"status": "error"', '"result":', '"summary":']
    leaks = [p for p in leak_patterns if p in run.response]
    run.extras["json_leaks"] = leaks
    assert not leaks, f"raw JSON patterns leaked into response: {leaks}"


def response_no_internal_names(llm, sc, sa, wc, cc, run):
    """Response text must not expose specialist class names or internal architecture (RS2)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("Plan a trip to Bali in July for 7 days flying from Singapore")

    found = [n for n in _INTERNAL_NAMES if n in run.response]
    run.extras["internal_names_found"] = found
    assert not found, f"internal names exposed in response: {found}"


def response_greeting_no_tool_calls(llm, sc, sa, wc, cc, run):
    """A greeting must be handled with plain text — no tool calls (RS3)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("Hi there!")
    msgs = _messages(run.orchestrator)

    specialist_calls = _get_specialist_calls(msgs)
    run.extras["specialist_calls"] = [name for name, _ in specialist_calls]
    assert not specialist_calls, f"specialist calls for a greeting: {run.extras['specialist_calls']}"
    assert run.response, "empty response to greeting"


def response_capability_question_no_tool_calls(llm, sc, sa, wc, cc, run):
    """A capability question must be handled conversationally — no tool calls (RS4)."""
    run.orchestrator = _make_orchestrator(llm, sc, sa, wc, cc)
    run.response = run.orchestrator.turn("What can you help me with?")
    msgs = _messages(run.orchestrator)

    specialist_calls = _get_specialist_calls(msgs)
    run.extras["specialist_calls"] = [name for name, _ in specialist_calls]
    assert not specialist_calls, f"specialist calls for a capability question: {run.extras['specialist_calls']}"
    assert run.response, "empty response to capability question"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import datetime as dt

    llm = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        extra_headers=resolve_model_config(settings.llm_model).extra_headers,
    )
    search_client = SearchClient(api_key=settings.tavily_api_key)
    serpapi_client = SerpApiClient(settings.serpapi_api_key)
    weather_client = WeatherClient()
    currency_client = CurrencyClient()

    all_tests = [
        # Section 1 — routing: specialist selection
        routing_no_explorer_for_decided_destination,
        routing_explorer_for_undecided_destination,
        routing_itinerary_requires_full_research_and_weather,
        routing_itinerary_requires_weather,
        routing_budget_after_research_and_transport,
        routing_no_artifact_without_explicit_request,
        routing_light_depth_for_overview,
        routing_full_escalation_from_light_before_itinerary,
        # Section 1 — routing: KS reuse
        routing_no_research_when_full_in_state,
        routing_no_weather_when_in_state,
        # Section 1 — routing: parallelisation
        routing_research_weather_transport_parallel,
        routing_multi_destination_weather_parallel,
        routing_two_research_not_in_same_turn,
        routing_budget_not_parallel_with_prerequisites,
        # Section 2 — argument quality + error handling
        explorer_no_retry_on_hard_failure,
        explorer_no_research_after_zero_candidates,
        explorer_query_strips_negations,
        weather_retry_uses_different_string_after_geocode_failure,
        weather_failure_does_not_block_other_city,
        weather_city_level_not_region_for_sikkim,
        weather_specific_date_range_when_dates_known,
        weather_called_for_all_cities_multi_destination,
        research_at_region_level_not_sub_city,
        research_failure_blocks_itinerary_and_budget,
        transport_round_trip_for_simple_return,
        transport_one_way_for_each_multi_city_leg,
        transport_no_reverse_when_outbound_is_ground_only,
        itinerary_destinations_in_travel_order,
        itinerary_missing_research_triggers_escalation_and_reinvocation,
        artifact_query_preserves_requirements,
        artifact_needs_data_gaps_resolved_before_reinvocation,
        # Section 3 — clarification
        clarification_not_asked_when_all_info_present,
        clarification_no_calls_when_intent_too_sparse,
        clarification_passport_not_asked_for_general_research,
        clarification_budget_tier_not_blocking,
        clarification_dates_refused_research_proceeds_weather_skipped,
        clarification_origin_refused_transport_skipped,
        # Section 4 — update_user_context
        uc_called_when_trip_info_provided,
        uc_not_called_for_greetings,
        uc_precedes_specialist_tools,
        uc_accumulates_intent_across_turns,
        # Section 5 — response quality
        response_no_raw_json,
        response_no_internal_names,
        response_greeting_no_tool_calls,
        response_capability_question_no_tool_calls,
    ]

    filters = sys.argv[1:]
    if filters:
        tests = [fn for fn in all_tests if any(f in fn.__name__ for f in filters)]
        if not tests:
            print(f"No tests matched filters: {filters}")
            print("Available tests:")
            for fn in all_tests:
                print(f"  {fn.__name__}")
            return
    else:
        tests = all_tests

    results = []
    for fn in tests:
        print(f"  {fn.__name__} ... ", end="", flush=True)
        result = run_test(fn, llm, search_client, serpapi_client, weather_client, currency_client)
        results.append(result)
        print("PASS" if result["passed"] else f"FAIL  {result['details']}")

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n{passed}/{total} passed")

    output = {
        "specialist": "Orchestrator",
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model": settings.llm_model,
        "results": results,
        "summary": {"passed": passed, "failed": total - passed, "total": total},
    }

    results_dir = Path(__file__).parent / "results" / "orchestrator"
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = results_dir / f"{ts}.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
