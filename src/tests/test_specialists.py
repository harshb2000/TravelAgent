"""
Tests for specialist agents and their wrapper tools.
Each specialist section follows the TDD pattern from the plan.
"""
import json
import pytest
from unittest.mock import MagicMock, patch, call

from clients.llm_client import LLMClient
from tools.base import BaseTool
from models.knowledge_state import (
    DestinationCandidate,
    KnowledgeState,
    UserContext,
)


# ---------------------------------------------------------------------------
# Test helpers shared across specialists
# ---------------------------------------------------------------------------

def make_llm() -> MagicMock:
    return MagicMock(spec=LLMClient)


def stop_msg(content: str) -> dict:
    return {"role": "assistant", "content": content, "finish_reason": "stop"}


def tool_call_msg(calls: list[dict]) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "finish_reason": "tool_calls",
        "tool_calls": [
            {
                "id": c["id"],
                "type": "function",
                "function": {"name": c["name"], "arguments": json.dumps(c.get("args", {}))},
            }
            for c in calls
        ],
    }


def _candidate(name: str, turn: int = 0, query: str = "beach trip") -> DestinationCandidate:
    c = DestinationCandidate(
        name=name, country="TestCountry", vibe_tags=["beach"],
        rationale=f"Beautiful {name}", source_url="http://example.com",
        query=query,
    )
    c.added_at = turn
    return c


# ===========================================================================
# Phase 5b: ExplorerSpecialist
# ===========================================================================

from specialists.explorer import ExplorerSpecialist, EXPLORER_CACHE_THRESHOLD
from tools.explorer_wrapper import ExplorerWrapperTool


def _valid_candidate_json(name: str = "Prague", country: str = "Czech Republic") -> str:
    return json.dumps([{
        "name": name,
        "country": country,
        "vibe_tags": ["city", "culture"],
        "rationale": f"Great city trip to {name}",
        "source_url": "http://example.com",
        "query": "city trip Europe",
        # added_at intentionally omitted — system-managed field
    }])


# ---- ExplorerSpecialist.run() output structure ----

def test_explorer_run_parses_candidate_list():
    """Stub LLM returns a valid candidate JSON; run() produces DestinationCandidates with wordset."""
    llm = make_llm()
    llm.chat.return_value = stop_msg(_valid_candidate_json("Prague"))

    specialist = ExplorerSpecialist(llm, [])
    results = specialist.run("city trips Europe", max_results=1)

    assert len(results) == 1
    assert results[0].name == "Prague"
    assert results[0].country == "Czech Republic"
    assert isinstance(results[0].wordset, frozenset)
    assert len(results[0].wordset) > 0


def test_explorer_run_dispatches_web_search():
    """Stub LLM does one web_search call then returns final answer."""
    from tools.web_search import WebSearchTool

    llm = make_llm()
    search_tool = MagicMock(spec=WebSearchTool)
    search_tool.name = "web_search"
    search_tool.execute.return_value = {"results": [{"title": "Prague", "url": "http://ex.com", "content": "great", "score": 0.9}]}
    search_tool.to_llm_definition.return_value = {"type": "function", "function": {"name": "web_search", "parameters": {}}}

    llm.chat.side_effect = [
        tool_call_msg([{"id": "c1", "name": "web_search", "args": {"query": "city trips"}}]),
        stop_msg(_valid_candidate_json("Prague")),
    ]

    specialist = ExplorerSpecialist(llm, [search_tool])
    results = specialist.run("city trips Europe", max_results=1)

    search_tool.execute.assert_called_once()
    assert len(results) == 1


# ---- Wrapper pre-firing check: blocklist exclusion ----

def test_explorer_wrapper_excludes_blocklisted_candidates():
    """Candidates whose name is in blocklist are excluded before Jaccard runs."""
    llm = make_llm()
    llm.chat.return_value = stop_msg(_valid_candidate_json("Bangkok"))

    ks = KnowledgeState()
    # Add "Thailand" candidate that will be in blocklist
    thailand_candidate = _candidate("Thailand", turn=1, query="beach")
    ks.add_candidates([thailand_candidate])

    uc = UserContext("not Thailand, prefer Europe")
    specialist = ExplorerSpecialist(llm, [])
    wrapper = ExplorerWrapperTool(specialist, ks, uc)

    result = wrapper.execute(query="beach trip from Europe")

    # Thailand should not appear in summary
    summary = result.get("summary", "")
    assert "Thailand" not in summary


# ---- Wrapper pre-firing check: full cache hit, sorted by relevance ----

def test_explorer_wrapper_full_cache_hit_returns_highest_scoring():
    """When more cached candidates pass the threshold than max_results, the most relevant ones are returned."""
    llm = make_llm()
    ks = KnowledgeState()

    # High relevance: query closely matches "city culture Europe"
    high = DestinationCandidate(
        name="Prague", country="Czech Republic",
        vibe_tags=["city", "culture"],
        rationale="vibrant city culture trip in Europe",
        source_url="http://ex.com",
        query="city culture Europe",
    )
    # Low relevance: only "city" overlaps
    low = DestinationCandidate(
        name="Bangkok", country="Thailand",
        vibe_tags=["city", "budget"],
        rationale="cheap city street food",
        source_url="http://ex.com",
        query="cheap city budget Asia",
    )
    ks.add_candidates([low, high])  # low added first — insertion order would return it first without sorting

    uc = UserContext("city culture Europe")
    specialist = ExplorerSpecialist(llm, [])
    wrapper = ExplorerWrapperTool(specialist, ks, uc)

    result = wrapper.execute(query="city culture Europe", max_results=1)

    llm.chat.assert_not_called()
    assert "Prague" in result["summary"]
    assert "Bangkok" not in result["summary"]


def test_explorer_wrapper_full_cache_hit_skips_specialist():
    """K >= max_results candidates above threshold → specialist not called."""
    llm = make_llm()
    ks = KnowledgeState()
    # Add candidates with query that closely matches incoming query
    for i in range(5):
        c = DestinationCandidate(
            name=f"City{i}", country="Europe",
            vibe_tags=["city", "culture"],
            rationale="vibrant city culture trip",
            source_url="http://ex.com",
            query="city culture Europe trip",
        )
        c.added_at = i
        ks.add_candidates([c])

    uc = UserContext("city culture Europe")
    specialist = ExplorerSpecialist(llm, [])
    wrapper = ExplorerWrapperTool(specialist, ks, uc)

    result = wrapper.execute(query="city culture Europe trip", max_results=5)

    # LLM should NOT have been called (cache hit)
    llm.chat.assert_not_called()
    assert result.get("cached", False) is True or "cached" in result.get("summary", "").lower() or result.get("from_cache") is True


# ---- Wrapper pre-firing check: partial cache hit ----

def test_explorer_wrapper_partial_cache_hit_reduces_max_results():
    """K < max_results matching candidates → specialist called with max_results = max_results - K."""
    llm = make_llm()
    llm.chat.return_value = stop_msg(_valid_candidate_json("Lisbon", "Portugal"))

    ks = KnowledgeState()
    # 2 matching candidates (query closely matches)
    for name in ["Prague", "Berlin"]:
        c = DestinationCandidate(
            name=name, country="Europe",
            vibe_tags=["city", "culture"],
            rationale="vibrant city culture trip",
            source_url="http://ex.com",
            query="city culture Europe trip",
        )
        c.added_at = 1
        ks.add_candidates([c])

    uc = UserContext("city culture Europe")
    specialist = ExplorerSpecialist(llm, [])
    wrapper = ExplorerWrapperTool(specialist, ks, uc)

    # Request 5, 2 cached → specialist should run for 3 more
    result = wrapper.execute(query="city culture Europe trip", max_results=5)

    llm.chat.assert_called()
    # Specialist invocation should have used reduced max_results
    specialist_call_args = specialist._last_run_max_results  # set by specialist.run()
    assert specialist_call_args == 3


# ---- Negative constraints in task string ----

def test_explorer_wrapper_negative_constraints_in_task():
    """Blocklist terms from UserContext appear as explicit exclusions in the specialist task."""
    llm = make_llm()
    llm.chat.return_value = stop_msg(_valid_candidate_json("Prague"))

    ks = KnowledgeState()
    uc = UserContext("not Thailand, not Bali")
    specialist = ExplorerSpecialist(llm, [])
    wrapper = ExplorerWrapperTool(specialist, ks, uc)

    wrapper.execute(query="beach trip")

    # The task passed to specialist should contain the negative constraints
    assert specialist._last_run_query is not None
    assert "thailand" in specialist._last_run_query.lower() or "bali" in specialist._last_run_query.lower()


# ---- Wrapper exception handling ----

def test_explorer_wrapper_specialist_exception_returns_error_string():
    """specialist.run() raises → wrapper returns error string; knowledge not updated."""
    llm = make_llm()
    ks = KnowledgeState()
    uc = UserContext("city trip")
    specialist = ExplorerSpecialist(llm, [])
    specialist.run = MagicMock(side_effect=RuntimeError("API error"))
    wrapper = ExplorerWrapperTool(specialist, ks, uc)

    result = wrapper.execute(query="city trip Europe")

    assert "error" in result.get("summary", "").lower() or result.get("status") == "error"
    assert len(ks.candidates) == 0
