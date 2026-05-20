import json
import pytest
from unittest.mock import MagicMock

from tests.helpers import make_llm, stop_msg, tool_call_msg
from models.knowledge_state import DestinationCandidate, KnowledgeState, UserContext
from specialists.explorer import ExplorerSpecialist, EXPLORER_CACHE_THRESHOLD
from tools.explorer_wrapper import ExplorerWrapperTool


def _beach_candidate(name: str, turn: int = 0, query: str = "beach trip") -> DestinationCandidate:
    c = DestinationCandidate(
        name=name, country="TestCountry", vibe_tags=["beach"],
        rationale=f"Beautiful {name}", source_url="http://example.com",
        query=query,
    )
    c.added_at = turn
    return c


def _valid_candidate_json(name: str = "Prague", country: str = "Czech Republic") -> str:
    return json.dumps([{
        "name": name, "country": country,
        "vibe_tags": ["city", "culture"],
        "rationale": f"Great city trip to {name}",
        "source_url": "http://example.com",
        "query": "city trip Europe",
    }])


# ---- ExplorerSpecialist.run() ----

def test_explorer_run_parses_candidate_list():
    llm = make_llm()
    llm.chat.return_value = stop_msg(_valid_candidate_json())
    specialist = ExplorerSpecialist(llm, [])
    results = specialist.run("city trips Europe", max_results=1)
    assert len(results) == 1
    assert results[0].name == "Prague"
    assert results[0].country == "Czech Republic"
    assert isinstance(results[0].wordset, frozenset)
    assert len(results[0].wordset) > 0



# ---- Wrapper: blocklist exclusion ----

def test_explorer_wrapper_excludes_blocklisted_candidates():
    llm = make_llm()
    llm.chat.return_value = stop_msg(_valid_candidate_json("Bangkok"))
    ks = KnowledgeState()
    ks.add_candidates([_beach_candidate("Thailand", turn=1, query="beach")])
    uc = UserContext("not Thailand, prefer Europe")
    result = ExplorerWrapperTool(ExplorerSpecialist(llm, []), ks, uc).execute(query="beach trip from Europe")
    assert "Thailand" not in result.get("summary", "")


# ---- Wrapper: full cache hit sorted by relevance ----

def test_explorer_wrapper_full_cache_hit_returns_highest_scoring():
    llm = make_llm()
    ks = KnowledgeState()
    high = DestinationCandidate(
        name="Prague", country="Czech Republic", vibe_tags=["city", "culture"],
        rationale="vibrant city culture trip in Europe", source_url="http://ex.com",
        query="city culture Europe",
    )
    low = DestinationCandidate(
        name="Bangkok", country="Thailand", vibe_tags=["city", "budget"],
        rationale="cheap city street food", source_url="http://ex.com",
        query="cheap city budget Asia",
    )
    ks.add_candidates([low, high])
    uc = UserContext("city culture Europe")
    result = ExplorerWrapperTool(ExplorerSpecialist(llm, []), ks, uc).execute(query="city culture Europe", max_results=1)
    llm.chat.assert_not_called()
    assert "Prague" in result["summary"]
    assert "Bangkok" not in result["summary"]


def test_explorer_wrapper_full_cache_hit_skips_specialist():
    llm = make_llm()
    ks = KnowledgeState()
    for i in range(5):
        c = DestinationCandidate(
            name=f"City{i}", country="Europe", vibe_tags=["city", "culture"],
            rationale="vibrant city culture trip", source_url="http://ex.com",
            query="city culture Europe trip",
        )
        c.added_at = i
        ks.add_candidates([c])
    uc = UserContext("city culture Europe")
    result = ExplorerWrapperTool(ExplorerSpecialist(llm, []), ks, uc).execute(query="city culture Europe trip", max_results=5)
    llm.chat.assert_not_called()
    assert result.get("from_cache") is True or "cached" in result.get("summary", "").lower()


# ---- Wrapper: partial cache hit ----

def test_explorer_wrapper_partial_cache_hit_reduces_max_results():
    llm = make_llm()
    llm.chat.return_value = stop_msg(_valid_candidate_json("Lisbon", "Portugal"))
    ks = KnowledgeState()
    for name in ["Prague", "Berlin"]:
        c = DestinationCandidate(
            name=name, country="Europe", vibe_tags=["city", "culture"],
            rationale="vibrant city culture trip", source_url="http://ex.com",
            query="city culture Europe trip",
        )
        c.added_at = 1
        ks.add_candidates([c])
    uc = UserContext("city culture Europe")
    specialist = ExplorerSpecialist(llm, [])
    ExplorerWrapperTool(specialist, ks, uc).execute(query="city culture Europe trip", max_results=5)
    llm.chat.assert_called()
    assert specialist._last_run_max_results == 3


# ---- Wrapper: negative constraints forwarded via user_context ----

def test_explorer_wrapper_negative_constraints_in_user_context():
    """Blocklist constraints reach the specialist through user_context, not embedded in the query."""
    llm = make_llm()
    llm.chat.return_value = stop_msg(_valid_candidate_json("Prague"))
    ks = KnowledgeState()
    uc = UserContext("not Thailand, not Bali")
    specialist = ExplorerSpecialist(llm, [])
    ExplorerWrapperTool(specialist, ks, uc).execute(query="beach trip")
    # Query stays clean — constraints are in user_context, not embedded in the query string
    assert "exclude" not in (specialist._last_run_query or "").lower()
    assert specialist._last_run_user_context is not None
    assert "thailand" in specialist._last_run_user_context.lower() or "bali" in specialist._last_run_user_context.lower()


# ---- Wrapper: exception handling ----

def test_explorer_wrapper_specialist_exception_returns_error():
    llm = make_llm()
    ks = KnowledgeState()
    uc = UserContext("city trip")
    specialist = ExplorerSpecialist(llm, [])
    specialist.run = MagicMock(side_effect=RuntimeError("API error"))
    result = ExplorerWrapperTool(specialist, ks, uc).execute(query="city trip Europe")
    assert "error" in result.get("summary", "").lower() or result.get("status") == "error"
    assert len(ks.candidates) == 0
