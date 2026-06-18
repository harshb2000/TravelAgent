#!/usr/bin/env python3
"""
Assertion-based evaluation for ExplorerSpecialist.

Group A: Output correctness (constraint compliance, deduplication, field completeness)
Group B: Search behavior (searches issued, parallelism for multi-region, query diversity)

Every test makes real LLM and real web search API calls.

Usage (from src/):
    python eval/explorer_specialist.py [filter ...]

Results saved to:
    src/eval/results/explorer_specialist_<timestamp>.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from clients.llm_client import LLMClient
from clients.search_client import SearchClient
from config.settings import settings
from models.knowledge_state import DestinationCandidate, build_wordset
from specialists.explorer import ExplorerSpecialist
from tools.web_search import WebSearchTool


# ---------------------------------------------------------------------------
# Run context — mutable per-test holder so run_test can read state after a failure
# ---------------------------------------------------------------------------

class _Run:
    def __init__(self):
        self.specialist: ExplorerSpecialist | None = None
        self.candidates: list[DestinationCandidate] = []


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


def _make_specialist(llm: LLMClient, search_client: SearchClient) -> ExplorerSpecialist:
    return ExplorerSpecialist(llm, [WebSearchTool(search_client)])


def _history_messages(specialist: ExplorerSpecialist) -> list[dict]:
    return specialist._agent._history.messages


def _search_iterations(messages: list[dict]) -> list[list[dict]]:
    """web_search calls grouped by assistant turn; each turn = one tool-use round."""
    iters = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            searches = [tc for tc in msg["tool_calls"] if tc["function"]["name"] == "web_search"]
            if searches:
                iters.append(searches)
    return iters


def _all_search_queries(messages: list[dict]) -> list[str]:
    queries = []
    for iteration in _search_iterations(messages):
        for tc in iteration:
            args = json.loads(tc["function"].get("arguments", "{}"))
            queries.append(args.get("query", ""))
    return queries


def _jaccard(a: frozenset, b: frozenset) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 1.0


# ---------------------------------------------------------------------------
# Result serialization
# ---------------------------------------------------------------------------

def _serialize_search_calls(iters: list[list[dict]]) -> list[list[dict]]:
    return [
        [
            {
                "name": tc["function"]["name"],
                "args": json.loads(tc["function"].get("arguments", "{}")),
            }
            for tc in iteration
        ]
        for iteration in iters
    ]


def _serialize_candidates(candidates: list[DestinationCandidate]) -> list[dict]:
    return [
        {
            "name": c.name,
            "country": c.country,
            "vibe_tags": c.vibe_tags,
            "rationale": c.rationale,
            "source_url": c.source_url,
        }
        for c in candidates
    ]


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_test(fn, llm, search_client) -> dict:
    name = fn.__name__
    run = _Run()
    try:
        fn(llm, search_client, run)
        msgs = _history_messages(run.specialist) if run.specialist else []
        iters = _search_iterations(msgs)
        return {
            "name": name,
            "passed": True,
            "details": "",
            "search_calls": _serialize_search_calls(iters),
            "candidates": _serialize_candidates(run.candidates),
        }
    except AssertionError as e:
        msgs = _history_messages(run.specialist) if run.specialist else []
        iters = _search_iterations(msgs)
        return {
            "name": name,
            "passed": False,
            "details": str(e),
            "search_calls": _serialize_search_calls(iters),
            "candidates": _serialize_candidates(run.candidates),
        }
    except Exception as e:
        msgs = _history_messages(run.specialist) if run.specialist else []
        iters = _search_iterations(msgs)
        return {
            "name": name,
            "passed": False,
            "details": f"EXCEPTION: {type(e).__name__}: {e}",
            "search_calls": _serialize_search_calls(iters),
            "candidates": _serialize_candidates(run.candidates),
        }


# ---------------------------------------------------------------------------
# Group A — Output correctness
# ---------------------------------------------------------------------------

def existing_candidates_not_repeated(llm, search_client, run):
    """Destinations listed in already_suggested must not appear in output (A1)."""
    existing = [
        DestinationCandidate(name="Bali", country="Indonesia"),
        DestinationCandidate(name="Tokyo", country="Japan"),
        DestinationCandidate(name="Lisbon", country="Portugal"),
    ]
    run.specialist = _make_specialist(llm, search_client)
    run.candidates = run.specialist.run(
        query="beach destinations in Southeast Asia or Southern Europe",
        max_results=3,
        existing_candidates=existing,
    )
    existing_names = {c.name.lower() for c in existing}
    repeated = [c.name for c in run.candidates if c.name.lower() in existing_names]
    assert not repeated, f"repeated existing candidates: {repeated}"


def negative_constraints_not_violated(llm, search_client, run):
    """Candidates must not come from countries excluded in user_context (A2)."""
    run.specialist = _make_specialist(llm, search_client)
    run.candidates = run.specialist.run(
        query="city trips in Europe",
        max_results=4,
        user_context="User wants European cities. Does not want France or Spain.",
    )
    blocked_countries = {"france", "spain"}
    violations = [c.name for c in run.candidates if c.country.lower() in blocked_countries]
    assert not violations, f"candidates from excluded countries: {violations}"


def no_duplicate_destinations_in_output(llm, search_client, run):
    """No two candidates may share the same destination name (A2b)."""
    run.specialist = _make_specialist(llm, search_client)
    run.candidates = run.specialist.run(query="city trips in Asia", max_results=5)
    names = [c.name.lower() for c in run.candidates]
    seen: set[str] = set()
    duplicates = []
    for n in names:
        if n in seen:
            duplicates.append(n)
        seen.add(n)
    assert not duplicates, f"duplicate destinations in output: {duplicates}"


def all_candidates_have_required_fields(llm, search_client, run):
    """Every candidate must have non-empty name, country, vibe_tags, rationale, source_url (A3)."""
    run.specialist = _make_specialist(llm, search_client)
    run.candidates = run.specialist.run(
        query="destinations known for street food and vibrant markets", max_results=4
    )
    assert run.candidates, "specialist returned no candidates"
    for c in run.candidates:
        assert c.name, f"empty name: {c}"
        assert c.country, f"'{c.name}': empty country"
        assert c.vibe_tags, f"'{c.name}': empty vibe_tags"
        assert c.rationale, f"'{c.name}': empty rationale"
        assert c.source_url, f"'{c.name}': empty source_url"


# ---------------------------------------------------------------------------
# Group B — Search behavior
# ---------------------------------------------------------------------------

def at_least_one_search_is_issued(llm, search_client, run):
    """Specialist must call web_search at least once — candidates must not be hallucinated (B1)."""
    run.specialist = _make_specialist(llm, search_client)
    run.candidates = run.specialist.run(
        query="relaxing beach destinations in Southeast Asia", max_results=3
    )
    queries = _all_search_queries(_history_messages(run.specialist))
    assert queries, "no web_search calls found — candidates may be hallucinated from training data"


def multi_region_query_uses_parallel_searches(llm, search_client, run):
    """At least one iteration must contain multiple parallel web_search calls for a clearly
    multi-region query (B2). Southeast Asia and the Caribbean are named separately — a single
    combined query gives region-skewed results."""
    run.specialist = _make_specialist(llm, search_client)
    run.candidates = run.specialist.run(
        query="beach destinations in Southeast Asia or the Caribbean", max_results=5
    )
    iters = _search_iterations(_history_messages(run.specialist))
    has_parallel = any(len(it) > 1 for it in iters)
    query_log = [
        [json.loads(tc["function"].get("arguments", "{}")).get("query") for tc in it]
        for it in iters
    ]
    assert has_parallel, (
        f"expected parallel web_search calls for a clearly multi-region query, "
        f"but every iteration had only a single call. Iterations: {query_log}"
    )


def no_repeated_or_near_duplicate_search_queries(llm, search_client, run):
    """No two search queries may be identical or share >80% significant words (B3)."""
    run.specialist = _make_specialist(llm, search_client)
    run.candidates = run.specialist.run(
        query="scenic mountain destinations in Europe for hiking", max_results=4
    )
    queries = _all_search_queries(_history_messages(run.specialist))

    seen: set[str] = set()
    for q in queries:
        assert q not in seen, f"exact duplicate query issued: '{q}'"
        seen.add(q)

    wordsets = [(build_wordset(q), q) for q in queries]
    for i, (ws_i, q_i) in enumerate(wordsets):
        for j, (ws_j, q_j) in enumerate(wordsets):
            if j <= i:
                continue
            sim = _jaccard(ws_i, ws_j)
            assert sim <= 0.8, (
                f"near-duplicate queries (jaccard={sim:.2f} > 0.8): "
                f"'{q_i}' and '{q_j}'"
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import datetime as dt

    llm = _make_llm()
    search_client = SearchClient(api_key=settings.tavily_api_key)

    all_tests = [
        existing_candidates_not_repeated,
        negative_constraints_not_violated,
        no_duplicate_destinations_in_output,
        all_candidates_have_required_fields,
        at_least_one_search_is_issued,
        multi_region_query_uses_parallel_searches,
        no_repeated_or_near_duplicate_search_queries,
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
        "specialist": "ExplorerSpecialist",
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model": settings.llm_model,
        "results": results,
        "summary": {"passed": passed, "failed": total - passed, "total": total},
    }

    results_dir = Path(__file__).parent / "results" / "explorer_specialist"
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = results_dir / f"{ts}.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
