#!/usr/bin/env python3
"""
Assertion-based evaluation for DestinationResearchSpecialist.

Group A: Search count by depth (light=1, full cold=3-4, upgrade < 3 new)
Group B: User context sensitivity (visa gating, interest-tailored activities)
Group C: Output structure by depth (correct fields present/absent)

Every test makes real LLM and real web search API calls.

Usage (from src/):
    python eval/destination_research_specialist.py [filter ...]

Results saved to:
    src/eval/results/destination_research_specialist/<timestamp>.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from clients.llm_client import LLMClient
from clients.search_client import SearchClient
from config.settings import settings
from config.specialist_tuning import resolve_model_config
from models.knowledge_state import DestinationResearch
from specialists.destination_research import DestinationResearchSpecialist
from tools.web_search import WebSearchTool


# ---------------------------------------------------------------------------
# Run context
# ---------------------------------------------------------------------------

class _Run:
    def __init__(self):
        self.specialist: DestinationResearchSpecialist | None = None
        self.research: DestinationResearch | None = None
        self.extras: dict = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm() -> LLMClient:
    return LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        extra_headers=resolve_model_config(settings.llm_model).extra_headers,
    )


def _make_specialist(llm: LLMClient, search_client: SearchClient) -> DestinationResearchSpecialist:
    return DestinationResearchSpecialist(llm, [WebSearchTool(search_client)])


def _history_messages(specialist: DestinationResearchSpecialist) -> list[dict]:
    return specialist._agent._history.messages


def _count_web_searches(messages: list[dict]) -> int:
    return sum(
        1
        for msg in messages
        if msg.get("role") == "assistant" and msg.get("tool_calls")
        for tc in msg["tool_calls"]
        if tc["function"]["name"] == "web_search"
    )


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


def _serialize_research(research: DestinationResearch | None) -> dict | None:
    if research is None:
        return None
    return research.model_dump()


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_test(fn, llm, search_client) -> dict:
    name = fn.__name__
    run = _Run()
    try:
        fn(llm, search_client, run)
        msgs = _history_messages(run.specialist) if run.specialist else []
        return {
            "name": name,
            "passed": True,
            "details": "",
            "turns": _serialize_turns(msgs),
            "research": _serialize_research(run.research),
            **run.extras,
        }
    except AssertionError as e:
        msgs = _history_messages(run.specialist) if run.specialist else []
        return {
            "name": name,
            "passed": False,
            "details": str(e),
            "turns": _serialize_turns(msgs),
            "research": _serialize_research(run.research),
            **run.extras,
        }
    except Exception as e:
        msgs = _history_messages(run.specialist) if run.specialist else []
        return {
            "name": name,
            "passed": False,
            "details": f"EXCEPTION: {type(e).__name__}: {e}",
            "turns": _serialize_turns(msgs),
            "research": _serialize_research(run.research),
            **run.extras,
        }


# ---------------------------------------------------------------------------
# Group A — Search count by depth
# ---------------------------------------------------------------------------

def light_depth_issues_exactly_one_search(llm, search_client, run):
    """Light mode must use its single iteration budget efficiently (A1)."""
    run.specialist = _make_specialist(llm, search_client)
    run.research = run.specialist.run("Tokyo", "light", "", max_iterations=2)
    count = _count_web_searches(_history_messages(run.specialist))
    assert count == 1, f"expected exactly 1 web_search for light depth, got {count}"


def full_cold_issues_three_to_four_searches(llm, search_client, run):
    """Full cold start must issue 3-5 distinct searches covering different topics (A2)."""
    run.specialist = _make_specialist(llm, search_client)
    run.research = run.specialist.run(
        "Tokyo", "full",
        "Travelling on Indian passport, interested in food and temples",
        max_iterations=2,
    )
    count = _count_web_searches(_history_messages(run.specialist))
    assert 3 <= count <= 5, f"expected 3-5 web_searches for full cold depth, got {count}"


# ---------------------------------------------------------------------------
# Group B — User context sensitivity
# ---------------------------------------------------------------------------

def visa_populated_when_nationality_given(llm, search_client, run):
    """visa_complexity must be populated when a passport is stated in user_context (B1)."""
    run.specialist = _make_specialist(llm, search_client)
    run.research = run.specialist.run(
        "Vietnam", "full", "Travelling on Indian passport", max_iterations=4
    )
    r = run.research
    assert r.visa_complexity, (
        "visa_complexity is None or empty — expected visa info for Indian passport"
    )
    has_india_key = any("india" in k.lower() for k in r.visa_complexity)
    assert has_india_key, (
        f"no key in visa_complexity references Indian passport. "
        f"Keys found: {list(r.visa_complexity.keys())}"
    )


def visa_absent_when_no_nationality_given(llm, search_client, run):
    """visa_complexity must be None/empty when no nationality is in user_context (B2)."""
    run.specialist = _make_specialist(llm, search_client)
    run.research = run.specialist.run(
        "Vietnam", "full", "Interested in street food and history", max_iterations=4
    )
    r = run.research
    assert not r.visa_complexity, (
        f"visa_complexity should be None/empty when no nationality is given, "
        f"got keys: {list(r.visa_complexity.keys()) if r.visa_complexity else '(none)'}"
    )


def activities_tailored_to_stated_interests(llm, search_client, run):
    """activities must be non-empty and include tags matching stated interests (B3).

    Matching is substring-based in both directions: a tag matches if any interest keyword
    is a substring of the tag, or the tag is a substring of any keyword.
    Per-activity match counts are saved to run.extras for inspection.
    """
    run.specialist = _make_specialist(llm, search_client)
    run.research = run.specialist.run(
        "Bali", "full", "Loves surfing and local food experiences", max_iterations=4
    )
    r = run.research
    assert r.activities, "activities is None or empty — expected interest-tailored list"

    interest_keywords = {"surf", "outdoor", "water", "food", "culinary", "eating", "cooking", "beach"}

    def _tag_matches(tag: str) -> bool:
        t = tag.lower()
        return any(kw in t or t in kw for kw in interest_keywords)

    match_counts = {
        a.name: sum(1 for t in a.tags if _tag_matches(t))
        for a in r.activities
    }
    run.extras["activity_tag_matches"] = match_counts

    assert any(v > 0 for v in match_counts.values()), (
        f"no activity tags matched stated interests (surfing, local food) via substring. "
        f"All tags: {sorted({t.lower() for a in r.activities for t in a.tags})}"
    )


# ---------------------------------------------------------------------------
# Group C — Output structure by depth
# ---------------------------------------------------------------------------

def light_output_has_correct_structure(llm, search_client, run):
    """Light depth must populate vibe/top_attractions/summary and leave all other fields null (C1)."""
    run.specialist = _make_specialist(llm, search_client)
    run.research = run.specialist.run("Paris", "light", "", max_iterations=2)
    r = run.research
    assert r.vibe, "vibe is empty"
    assert r.top_attractions, "top_attractions is empty"
    assert r.summary, "summary is empty"
    assert r.safety_summary is None, f"safety_summary should be None for light depth, got: {r.safety_summary}"
    assert r.visa_complexity is None, (
        f"visa_complexity should be None for light depth, got: {list(r.visa_complexity.keys())}"
    )
    assert r.festivals is None, f"festivals should be None for light depth, got: {r.festivals}"
    assert r.notable_areas is None, f"notable_areas should be None for light depth, got: {r.notable_areas}"
    assert r.activities is None, f"activities should be None for light depth, got: {r.activities}"


def full_output_has_all_fields_populated(llm, search_client, run):
    """Full depth must populate every field, with valid structure on notable_areas (C2)."""
    run.specialist = _make_specialist(llm, search_client)
    run.research = run.specialist.run(
        "Paris", "full",
        "Travelling on UK passport, interested in art and food",
        max_iterations=4,
    )
    r = run.research
    assert r.vibe, "vibe is empty"
    assert r.top_attractions, "top_attractions is empty"
    assert r.summary, "summary is empty"
    assert r.safety_summary is not None, "safety_summary is None"
    assert r.festivals is not None, "festivals is None"
    assert r.notable_areas, "notable_areas is None or empty"
    for area_name, area in r.notable_areas.items():
        assert area.description, f"notable_area '{area_name}': empty description"
        assert area.highlights, f"notable_area '{area_name}': empty highlights list"
    assert r.activities, "activities is None or empty"
    assert r.visa_complexity, (
        "visa_complexity is None — expected info for UK passport travelling to France"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import datetime as dt

    llm = _make_llm()
    search_client = SearchClient(api_key=settings.tavily_api_key)

    all_tests = [
        light_depth_issues_exactly_one_search,
        full_cold_issues_three_to_four_searches,
        visa_populated_when_nationality_given,
        visa_absent_when_no_nationality_given,
        activities_tailored_to_stated_interests,
        light_output_has_correct_structure,
        full_output_has_all_fields_populated,
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
        result = run_test(fn, llm, search_client)
        results.append(result)
        print("PASS" if result["passed"] else f"FAIL  {result['details']}")

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n{passed}/{total} passed")

    output = {
        "specialist": "DestinationResearchSpecialist",
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model": settings.llm_model,
        "results": results,
        "summary": {"passed": passed, "failed": total - passed, "total": total},
    }

    results_dir = Path(__file__).parent / "results" / "destination_research_specialist"
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = results_dir / f"{ts}.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
