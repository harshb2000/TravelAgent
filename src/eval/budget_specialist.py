#!/usr/bin/env python3
"""
Assertion-based evaluation for BudgetSpecialist.

A1: currency_convert called when home currency is in user_context
A2: currency_convert not called when no home currency given
A3: flight/return round-trip counted once, not twice
A4: parallel web_searches when no existing budget data

Every test makes real LLM calls; A3 uses a pre-built travel_costs string so no
flight API is needed. A2 and A3 use no web or currency APIs either.

Usage (from src/):
    python eval/budget_specialist.py [filter ...]

Results saved to:
    src/eval/results/budget_specialist/<timestamp>.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from clients.currency_client import CurrencyClient
from clients.llm_client import LLMClient
from clients.search_client import SearchClient
from config.settings import settings
from models.specialist_outputs import BudgetSpecialistOutput
from specialists.budget import BudgetSpecialist
from tools.calculate import CalculateTool
from tools.currency_convert import CurrencyConvertTool
from tools.web_search import WebSearchTool


# ---------------------------------------------------------------------------
# Run context
# ---------------------------------------------------------------------------

class _Run:
    def __init__(self):
        self.specialist: BudgetSpecialist | None = None
        self.output: BudgetSpecialistOutput | None = None
        self.extras: dict = {}


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


def _make_specialist(llm: LLMClient, search_client: SearchClient) -> BudgetSpecialist:
    return BudgetSpecialist(llm, [
        WebSearchTool(search_client),
        CurrencyConvertTool(CurrencyClient()),
        CalculateTool(),
    ])


def _history_messages(specialist: BudgetSpecialist) -> list[dict]:
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


def _serialize_output(output: BudgetSpecialistOutput | None) -> dict | None:
    if output is None:
        return None
    return output.model_dump()


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
            "output": _serialize_output(run.output),
            **run.extras,
        }
    except AssertionError as e:
        msgs = _history_messages(run.specialist) if run.specialist else []
        return {
            "name": name,
            "passed": False,
            "details": str(e),
            "turns": _serialize_turns(msgs),
            "output": _serialize_output(run.output),
            **run.extras,
        }
    except Exception as e:
        msgs = _history_messages(run.specialist) if run.specialist else []
        return {
            "name": name,
            "passed": False,
            "details": f"EXCEPTION: {type(e).__name__}: {e}",
            "turns": _serialize_turns(msgs),
            "output": _serialize_output(run.output),
            **run.extras,
        }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def currency_convert_called_when_home_currency_given(llm, search_client, run):
    """currency_convert must be called and target INR when home currency is in user_context (A1)."""
    run.specialist = _make_specialist(llm, search_client)
    run.output = run.specialist.run(
        query="2 people, 7 nights Tokyo, mid-range",
        user_context="Home currency INR, budget ₹2.5L",
    )
    msgs = _history_messages(run.specialist)
    cc_calls = _get_tool_calls(msgs, "currency_convert")
    run.extras["currency_convert_calls"] = [_parse_args(tc) for tc in cc_calls]
    assert cc_calls, "no currency_convert call found — expected conversion to INR"
    all_targets = [c for tc in cc_calls for c in _parse_args(tc).get("to_currencies", [])]
    assert "INR" in all_targets, (
        f"currency_convert called but INR not in any to_currencies. "
        f"Targets seen: {all_targets}"
    )


def currency_convert_not_called_when_no_home_currency(llm, search_client, run):
    """currency_convert must not be called when query and user_context are USD-only (A2)."""
    run.specialist = _make_specialist(llm, search_client)
    run.output = run.specialist.run(
        query="1 person, 5 nights Bali, budget $800",
        user_context="",
    )
    msgs = _history_messages(run.specialist)
    cc_calls = _get_tool_calls(msgs, "currency_convert")
    assert not cc_calls, (
        f"unexpected currency_convert calls — no home currency was given. "
        f"Args: {[_parse_args(tc) for tc in cc_calls]}"
    )


def flight_return_round_trip_counted_once_not_twice(llm, search_client, run):
    """Two flight/return entries at $900 each represent one purchase — total must be $900, not $1800 (A3).

    travel_costs is pre-built to mirror what the budget wrapper produces:
    two flight/return lines at the same price, annotated '(round-trip price, count once)'.
    """
    travel_costs = (
        "  Mumbai to Tokyo (2026-07-15): flight/return $900 (round-trip price, count once)\n"
        "  Tokyo to Mumbai (2026-07-22): flight/return $900 (round-trip price, count once)"
    )
    run.specialist = _make_specialist(llm, search_client)
    run.output = run.specialist.run(
        query="1 person, 3 nights Tokyo, flying from Mumbai round-trip",
        travel_costs=travel_costs,
    )
    msgs = _history_messages(run.specialist)
    calc_calls = [_parse_args(tc) for tc in _get_tool_calls(msgs, "calculate")]
    run.extras["calculate_calls"] = calc_calls

    breakdown = run.output.breakdown if run.output else ""
    assert "1800" not in breakdown and "1,800" not in breakdown, (
        "breakdown contains $1,800 — flight/return $900 round-trip appears to be counted twice"
    )
    flight_calcs = [c for c in calc_calls if "flight" in c.get("label", "").lower()]
    doubled = [c for c in flight_calcs if "1800" in c.get("expression", "") or c.get("expression", "") in ("900+900", "900 + 900", "2*900", "2 * 900", "900*2", "900 * 2")]
    assert not doubled, (
        f"calculate expression suggests flight/return was doubled: {doubled}"
    )


def parallel_web_searches_issued_when_no_existing_budget(llm, search_client, run):
    """When no existing_budget is given, searches for independent cost categories must be
    issued in a single parallel iteration, not serialised across multiple rounds (A4)."""
    run.specialist = _make_specialist(llm, search_client)
    run.output = run.specialist.run(
        query="1 person, 5 nights Paris",
        existing_budget=None,
    )
    msgs = _history_messages(run.specialist)
    parallel_found = any(
        sum(1 for tc in msg["tool_calls"] if tc["function"]["name"] == "web_search") > 1
        for msg in msgs
        if msg.get("role") == "assistant" and msg.get("tool_calls")
    )
    all_search_queries = [
        _parse_args(tc).get("query", "")
        for tc in _get_tool_calls(msgs, "web_search")
    ]
    run.extras["web_search_queries"] = all_search_queries
    assert parallel_found, (
        f"no iteration had multiple parallel web_search calls — "
        f"cost category searches appear to be serialised. "
        f"Queries issued: {all_search_queries}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import datetime as dt

    llm = _make_llm()
    search_client = SearchClient(api_key=settings.tavily_api_key)

    all_tests = [
        currency_convert_called_when_home_currency_given,
        currency_convert_not_called_when_no_home_currency,
        flight_return_round_trip_counted_once_not_twice,
        parallel_web_searches_issued_when_no_existing_budget,
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
        "specialist": "BudgetSpecialist",
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model": settings.llm_model,
        "results": results,
        "summary": {"passed": passed, "failed": total - passed, "total": total},
    }

    results_dir = Path(__file__).parent / "results" / "budget_specialist"
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = results_dir / f"{ts}.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
