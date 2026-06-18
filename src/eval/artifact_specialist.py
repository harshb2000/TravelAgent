#!/usr/bin/env python3
"""
Assertion-based evaluation for ArtifactSpecialist.

Group A: Completeness check (major gap → missing_data; minor gap → proceed)
Group B: Iteration pattern (self_critique before file_write, filename convention,
         parallel fetches, stale/up-to-date re-fetch logic)

A-group tests use synthetic KnowledgeState — no external APIs needed.
B-group tests make real LLM calls; compiled tools read from synthetic KnowledgeState.
All tests that produce files clean up after themselves.

Usage (from src/):
    python eval/artifact_specialist.py [filter ...]

Results saved to:
    src/eval/results/artifact_specialist/<timestamp>.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from clients.llm_client import LLMClient
from config.settings import settings
from models.knowledge_state import (
    Activity,
    CostWithAttribution,
    DestinationBudget,
    DestinationResearch,
    KnowledgeState,
    NotableArea,
    StringWithAttribution,
)
from models.specialist_outputs import ArtifactOutput
from specialists.artifact import ArtifactSpecialist
from tools.base import BaseTool
from tools.file_write import FileWriteTool
from tools.get_compiled import (
    GetBudgetCompiledTool,
    GetCandidatesCompiledTool,
    GetResearchCompiledTool,
    GetRouteCompiledTool,
    GetWeatherCompiledTool,
)
from tools.get_itinerary import GetItineraryTool
from tools.self_critique import SelfCritiqueTool



# ---------------------------------------------------------------------------
# Run context
# ---------------------------------------------------------------------------

class _Run:
    def __init__(self):
        self.specialist: ArtifactSpecialist | None = None
        self.output: ArtifactOutput | None = None
        self.extras: dict = {}


# ---------------------------------------------------------------------------
# KnowledgeState builders
# ---------------------------------------------------------------------------

def _research(destination: str, country: str = "Japan", minor_gaps: bool = False) -> DestinationResearch:
    activities = [
        Activity(
            name="Temple Visit",
            tags=["cultural", "outdoor"],
            indoor=False,
            duration_min=None if minor_gaps else 90,
            source_url=None if minor_gaps else "https://example.com/temple",
        ),
        Activity(
            name="Street Food Tour",
            tags=["food", "outdoor"],
            indoor=False,
            duration_min=120,
            source_url="https://example.com/food",
        ),
    ]
    return DestinationResearch(
        name=destination,
        country=country,
        depth="full",
        vibe=f"{destination} blends ancient tradition with modern energy.",
        top_attractions=["Grand Temple", "Central Market", "Old Quarter"],
        summary=f"A must-visit destination with rich culture and diverse food scene.",
        safety_summary=StringWithAttribution(text="Generally safe for tourists.", source_url=None),
        festivals=["Spring Lantern Festival (April)"],
        notable_areas={
            "Old Quarter": NotableArea(
                description="Historic district with temples and street food.",
                highlights=["Grand Temple", "Night Market"],
                source_url=None,
            )
        },
        activities=activities,
    )


def _budget(destination: str) -> DestinationBudget:
    return DestinationBudget(
        accommodation={"mid-range hotel": CostWithAttribution(amount=100.0, source_url=None)},
        food={"street food + restaurants": CostWithAttribution(amount=25.0, source_url=None)},
        local_transport={"metro day pass": CostWithAttribution(amount=5.0, source_url=None)},
        activities={"temple entry": CostWithAttribution(amount=8.0, source_url=None)},
    )


def _ks_research_only(destination: str, minor_gaps: bool = False) -> KnowledgeState:
    ks = KnowledgeState()
    ks.update_research(destination, _research(destination, minor_gaps=minor_gaps))
    return ks


def _ks_research_and_budget(destination: str) -> KnowledgeState:
    ks = _ks_research_only(destination)
    ks.update_destination_budget(destination, _budget(destination))
    return ks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm() -> LLMClient:
    return LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        extra_headers=settings.llm_extra_headers,
    )


def _make_tools(llm: LLMClient, ks: KnowledgeState) -> list[BaseTool]:
    return [
        GetResearchCompiledTool(ks),
        GetBudgetCompiledTool(ks),
        GetWeatherCompiledTool(ks),
        GetRouteCompiledTool(ks),
        GetItineraryTool(ks),
        GetCandidatesCompiledTool(ks),
        SelfCritiqueTool(llm),
        FileWriteTool(),
    ]


def _make_specialist(llm: LLMClient, ks: KnowledgeState) -> ArtifactSpecialist:
    return ArtifactSpecialist(llm, _make_tools(llm, ks))


def _history_messages(specialist: ArtifactSpecialist) -> list[dict]:
    return specialist._agent._history.messages


def _get_tool_calls(messages: list[dict], tool_name: str) -> list[dict]:
    return [
        tc
        for msg in messages
        if msg.get("role") == "assistant" and msg.get("tool_calls")
        for tc in msg["tool_calls"]
        if tc["function"]["name"] == tool_name
    ]


def _parse_args(tc: dict) -> dict:
    return json.loads(tc["function"].get("arguments", "{}"))


def _get_tool_result(messages: list[dict], call_id: str) -> dict | None:
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id") == call_id:
            try:
                return json.loads(msg.get("content", "{}"))
            except (json.JSONDecodeError, TypeError):
                return None
    return None


def _cleanup(file_path: str | None) -> None:
    if file_path:
        try:
            Path(file_path).unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Result serialization
# ---------------------------------------------------------------------------

def _serialize_turns(messages: list[dict]) -> list[list[dict]]:
    turns = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            turns.append([
                {
                    "name": tc["function"]["name"],
                    "args": json.loads(tc["function"].get("arguments", "{}")),
                }
                for tc in msg["tool_calls"]
            ])
    return turns


def _serialize_output(output: ArtifactOutput | None) -> dict | None:
    return output.model_dump() if output else None


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_test(fn, llm) -> dict:
    name = fn.__name__
    run = _Run()
    try:
        fn(llm, run)
        msgs = _history_messages(run.specialist) if run.specialist else []
        result = {
            "name": name,
            "passed": True,
            "details": "",
            "turns": _serialize_turns(msgs),
            "output": _serialize_output(run.output),
            **run.extras,
        }
    except AssertionError as e:
        msgs = _history_messages(run.specialist) if run.specialist else []
        result = {
            "name": name,
            "passed": False,
            "details": str(e),
            "turns": _serialize_turns(msgs),
            "output": _serialize_output(run.output),
            **run.extras,
        }
    except Exception as e:
        msgs = _history_messages(run.specialist) if run.specialist else []
        result = {
            "name": name,
            "passed": False,
            "details": f"EXCEPTION: {type(e).__name__}: {e}",
            "turns": _serialize_turns(msgs),
            "output": _serialize_output(run.output),
            **run.extras,
        }
    finally:
        _cleanup(run.output.file_path if run.output else None)
    return result


# ---------------------------------------------------------------------------
# Group A — Completeness check
# ---------------------------------------------------------------------------

def major_gap_produces_missing_data_not_file(llm, run):
    """When a critical section is absent, specialist must set missing_data and not write (A1).

    KnowledgeState has only weather for Kyoto — no destination research at all.
    A 'full travel document' request depends on research being present.
    """
    ks = KnowledgeState()  # no research for Kyoto, only weather marker in knowledge string
    run.specialist = _make_specialist(llm, ks)
    knowledge = (
        "Kyoto:\n"
        "  destination research: NOT AVAILABLE\n"
        "  weather 2026-07-15: [up to date] (forecast)"
    )
    run.output = run.specialist.run(
        query="Write a full travel document for my Kyoto trip",
        knowledge=knowledge,
    )
    msgs = _history_messages(run.specialist)
    fw_calls = _get_tool_calls(msgs, "file_write")
    run.extras["missing_data"] = run.output.missing_data
    run.extras["file_write_calls"] = len(fw_calls)

    assert run.output.missing_data, "missing_data is None or empty — expected major gap signal"
    assert run.output.file_path is None, (
        f"file_path is set despite major gap: {run.output.file_path}"
    )
    has_kyoto_ref = any("kyoto" in item.lower() for item in run.output.missing_data)
    assert has_kyoto_ref, (
        f"no missing_data item references 'Kyoto' — descriptions are too vague: {run.output.missing_data}"
    )
    assert not fw_calls, f"file_write called {len(fw_calls)} time(s) despite major gap"


def minor_gap_proceeds_to_write_file(llm, run):
    """Field-level gaps (duration_min=None) must not block document generation (A2).

    KnowledgeState has full research for Tokyo but some activities lack duration_min.
    A research-only document request should proceed and write a file.
    """
    ks = _ks_research_only("Tokyo", minor_gaps=True)
    run.specialist = _make_specialist(llm, ks)
    knowledge = "Tokyo [full]:\n  destination research: [stale]"
    run.output = run.specialist.run(
        query="Generate a destination research document for Tokyo",
        knowledge=knowledge,
    )
    assert run.output.file_path is not None, (
        "file_path is None — specialist may have flagged missing duration_min as a major gap"
    )
    assert run.output.missing_data is None, (
        f"missing_data set despite only field-level gaps: {run.output.missing_data}"
    )
    msgs = _history_messages(run.specialist)
    fw_calls = _get_tool_calls(msgs, "file_write")
    assert fw_calls, "no file_write call found"


def missing_data_descriptions_are_specific(llm, run):
    """missing_data items must name the destination or section, not be generic (A3).

    Research is present for Tokyo; budget and itinerary are absent.
    A 'full trip plan with budget and day-by-day schedule' needs both.
    """
    ks = _ks_research_only("Tokyo")
    run.specialist = _make_specialist(llm, ks)
    knowledge = (
        "Tokyo [full]:\n"
        "  destination research: [up to date]\n"
        "  budget: NOT AVAILABLE\n"
        "  itinerary: NOT AVAILABLE"
    )
    run.output = run.specialist.run(
        query="Create a full trip plan with budget and day-by-day schedule for Tokyo",
        knowledge=knowledge,
    )
    run.extras["missing_data"] = run.output.missing_data

    assert run.output.missing_data, "missing_data is None or empty — expected gap descriptions"
    assert len(run.output.missing_data) >= 2, (
        f"expected ≥ 2 missing_data items (budget + itinerary), got {len(run.output.missing_data)}: "
        f"{run.output.missing_data}"
    )
    _GENERIC = {"missing data", "incomplete information", "data missing", "not available"}
    for item in run.output.missing_data:
        is_generic = item.strip().lower() in _GENERIC
        has_keyword = any(kw in item.lower() for kw in ["tokyo", "budget", "itinerary", "schedule", "plan"])
        assert not is_generic and has_keyword, (
            f"missing_data item is too vague — no destination or section name: '{item}'"
        )


# ---------------------------------------------------------------------------
# Group B — Iteration pattern
# ---------------------------------------------------------------------------

def self_critique_precedes_file_write(llm, run):
    """self_critique must be called before file_write in every document-producing run (B1)."""
    ks = _ks_research_only("Tokyo")
    run.specialist = _make_specialist(llm, ks)
    knowledge = "Tokyo [full]:\n  destination research: [stale]"
    run.output = run.specialist.run(
        query="Write a destination research summary for Tokyo",
        knowledge=knowledge,
    )
    msgs = _history_messages(run.specialist)
    sc_calls = _get_tool_calls(msgs, "self_critique")
    fw_calls = _get_tool_calls(msgs, "file_write")
    assert sc_calls, "no self_critique call found — draft was not reviewed before writing"
    assert fw_calls, "no file_write call found"

    # Verify order by position in history
    def _first_pos(name: str) -> int:
        for i, msg in enumerate(msgs):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                if any(tc["function"]["name"] == name for tc in msg["tool_calls"]):
                    return i
        return float("inf")

    sc_pos = _first_pos("self_critique")
    fw_pos = _first_pos("file_write")
    assert sc_pos < fw_pos, (
        f"self_critique (turn {sc_pos}) does not precede file_write (turn {fw_pos})"
    )


def file_path_matches_file_write_return_value(llm, run):
    """output.file_path must exactly match the path returned by file_write — not fabricated (B2)."""
    ks = _ks_research_only("Tokyo")
    run.specialist = _make_specialist(llm, ks)
    knowledge = "Tokyo [full]:\n  destination research: [stale]"
    run.output = run.specialist.run(
        query="Write a destination research summary for Tokyo",
        knowledge=knowledge,
    )
    msgs = _history_messages(run.specialist)
    fw_calls = _get_tool_calls(msgs, "file_write")
    assert fw_calls, "no file_write call found"

    fw_result = _get_tool_result(msgs, fw_calls[0]["id"])
    actual_path = (fw_result or {}).get("path", "")
    run.extras["file_write_returned_path"] = actual_path
    run.extras["output_file_path"] = run.output.file_path

    assert run.output.file_path == actual_path, (
        f"output.file_path '{run.output.file_path}' does not match "
        f"file_write return '{actual_path}'"
    )


def multi_section_fetches_are_parallel(llm, run):
    """All needed compiled tools must be called in a single parallel iteration (B4)."""
    ks = _ks_research_and_budget("Tokyo")
    run.specialist = _make_specialist(llm, ks)
    knowledge = (
        "Tokyo [full]:\n"
        "  destination research: [stale]\n"
        "  budget: [stale]"
    )
    run.output = run.specialist.run(
        query="Write a full trip planning document for Tokyo including budget",
        knowledge=knowledge,
    )
    msgs = _history_messages(run.specialist)
    _GET_TOOLS = {
        "get_research_compiled", "get_budget_compiled", "get_weather_compiled",
        "get_route_compiled", "get_itinerary", "get_candidates_compiled",
    }
    parallel_found = any(
        sum(1 for tc in msg["tool_calls"] if tc["function"]["name"] in _GET_TOOLS) > 1
        for msg in msgs
        if msg.get("role") == "assistant" and msg.get("tool_calls")
    )
    fetch_turns = [
        [tc["function"]["name"] for tc in msg["tool_calls"] if tc["function"]["name"] in _GET_TOOLS]
        for msg in msgs
        if msg.get("role") == "assistant" and msg.get("tool_calls")
        if any(tc["function"]["name"] in _GET_TOOLS for tc in msg["tool_calls"])
    ]
    run.extras["fetch_turns"] = fetch_turns
    assert parallel_found, (
        f"no iteration had parallel get_* calls — fetches appear serialised. "
        f"Fetch turns: {fetch_turns}"
    )


def up_to_date_sections_not_re_fetched(llm, run):
    """Sections marked [up to date] in the knowledge string must not be re-fetched (B5).

    First run uses [stale] markers so the specialist fetches and the data enters history.
    Second run (same instance) uses [up to date] — the specialist must use history directly
    and issue no new get_research_compiled or get_budget_compiled calls.
    """
    ks = _ks_research_and_budget("Tokyo")
    run.specialist = _make_specialist(llm, ks)

    # First run — seed history with fetched data
    first_output = run.specialist.run(
        query="Write a research summary for Tokyo",
        knowledge="Tokyo [full]:\n  destination research: [stale]\n  budget: [stale]",
    )
    _cleanup(first_output.file_path if first_output else None)

    msgs_after_first = _history_messages(run.specialist)
    research_count_1 = len(_get_tool_calls(msgs_after_first, "get_research_compiled"))
    budget_count_1 = len(_get_tool_calls(msgs_after_first, "get_budget_compiled"))

    # Second run — same data now marked [up to date]
    run.output = run.specialist.run(
        query="Write another research summary for Tokyo",
        knowledge="Tokyo [full]:\n  destination research: [up to date]\n  budget: [up to date]",
    )
    msgs_after_second = _history_messages(run.specialist)

    new_research = len(_get_tool_calls(msgs_after_second, "get_research_compiled")) - research_count_1
    new_budget = len(_get_tool_calls(msgs_after_second, "get_budget_compiled")) - budget_count_1
    run.extras["new_get_research_calls"] = new_research
    run.extras["new_get_budget_calls"] = new_budget

    assert new_research == 0, (
        f"get_research_compiled called {new_research} time(s) in second run despite [up to date]"
    )
    assert new_budget == 0, (
        f"get_budget_compiled called {new_budget} time(s) in second run despite [up to date]"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import datetime as dt

    llm = _make_llm()

    all_tests = [
        major_gap_produces_missing_data_not_file,
        minor_gap_proceeds_to_write_file,
        missing_data_descriptions_are_specific,
        self_critique_precedes_file_write,
        file_path_matches_file_write_return_value,
        multi_section_fetches_are_parallel,
        up_to_date_sections_not_re_fetched,
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
        result = run_test(fn, llm)
        results.append(result)
        print("PASS" if result["passed"] else f"FAIL  {result['details']}")

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n{passed}/{total} passed")

    output = {
        "specialist": "ArtifactSpecialist",
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model": settings.llm_model,
        "results": results,
        "summary": {"passed": passed, "failed": total - passed, "total": total},
    }

    results_dir = Path(__file__).parent / "results" / "artifact_specialist"
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = results_dir / f"{ts}.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
