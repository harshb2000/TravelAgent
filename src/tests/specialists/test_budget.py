import json
import pytest
from unittest.mock import MagicMock

from tests.helpers import make_llm, stop_msg
from models.knowledge_state import KnowledgeState, DestinationBudget, CostWithAttribution, TravelOption, RouteKey, DateRange, UserContext
from specialists.budget import BudgetSpecialist
from tools.budget_wrapper import BudgetWrapperTool


# ---------------------------------------------------------------------------
# JSON builders
# ---------------------------------------------------------------------------

def _budget_json(
    breakdown: str = "Total (2 people, USD): $2,500",
    include_destination_budget: bool = True,
) -> str:
    destination_budget = None
    if include_destination_budget:
        destination_budget = {
            "accommodation": {"mid-range hotel": {"amount": 90.0, "source_url": "https://example.com"}},
            "food": {"sit-down restaurant": {"amount": 25.0, "source_url": None}},
            "local_transport": {"metro day pass": {"amount": 5.0, "source_url": None}},
            "activities": {"temple entry": {"amount": 10.0, "source_url": None}},
        }
    return json.dumps({"destination_budget": destination_budget, "breakdown": breakdown})


def _make_specialist(chat_return):
    llm = make_llm()
    llm.chat.return_value = chat_return
    return BudgetSpecialist(llm, []), llm


def _make_wrapper(
    ks: KnowledgeState | None = None,
    with_existing_budget: bool = False,
    user_context: str = "",
):
    ks = ks or KnowledgeState()
    if with_existing_budget:
        ks.update_destination_budget("Tokyo", DestinationBudget(
            accommodation={"hostel dorm": CostWithAttribution(amount=20.0, source_url=None)},
            food={"street food": CostWithAttribution(amount=8.0, source_url=None)},
            local_transport={},
            activities={},
        ))
    llm = make_llm()
    llm.chat.return_value = stop_msg(_budget_json())
    specialist = BudgetSpecialist(llm, [])
    uc = UserContext(user_context)
    return BudgetWrapperTool(specialist, ks, uc), specialist, ks, llm


# ---------------------------------------------------------------------------
# BudgetSpecialist.run() — output parsing
# ---------------------------------------------------------------------------

def test_budget_run_raises_on_invalid_structure():
    specialist, _ = _make_specialist(stop_msg('{"destination_budget": null}'))
    with pytest.raises(Exception):
        specialist.run("Tokyo budget")


# ---------------------------------------------------------------------------
# BudgetWrapperTool
# ---------------------------------------------------------------------------

def test_budget_wrapper_calls_update_when_new_data():
    wrapper, _, ks, _ = _make_wrapper()
    wrapper.execute(query="Tokyo 7 nights", destination="Tokyo", )
    assert ks.destinations.get("Tokyo") is not None
    assert ks.destinations["Tokyo"].budget is not None
    assert "mid-range hotel" in ks.destinations["Tokyo"].budget.accommodation


def test_budget_wrapper_skips_update_when_no_new_data():
    wrapper, _, ks, llm = _make_wrapper()
    llm.chat.return_value = stop_msg(_budget_json(include_destination_budget=False))
    wrapper.execute(query="rough Tokyo cost", destination="Tokyo", )
    assert "Tokyo" not in ks.destinations


def test_budget_wrapper_passes_existing_budget_in_context():
    wrapper, specialist, _, _ = _make_wrapper(with_existing_budget=True)
    wrapper.execute(query="Tokyo 7 nights", destination="Tokyo", )
    task = specialist._last_run_task
    assert task is not None
    assert "hostel dorm" in task
    assert "street food" in task


def test_budget_wrapper_travel_options_show_price_range_per_route_and_mode():
    ks = KnowledgeState()
    dr = DateRange.from_string("2026-07-13")
    any_dr = DateRange("any")
    ks.update_route("BOM Airport", "NRT Airport", dr, [
        TravelOption(mode="flight/return", origin="BOM Airport", destination="NRT Airport", cost_usd=820.0),
        TravelOption(mode="flight/one-way", origin="BOM Airport", destination="NRT Airport", cost_usd=450.0),
        TravelOption(mode="flight/one-way", origin="BOM Airport", destination="NRT Airport", cost_usd=520.0),
    ])
    ks.update_route("NRT Airport", "Tokyo", any_dr, [
        TravelOption(mode="metro", origin="NRT Airport", destination="Tokyo", cost_usd=15.0),
    ])

    wrapper, specialist, _, _ = _make_wrapper(ks=ks)
    wrapper.execute(query="Tokyo budget", destination="Tokyo")

    task = specialist._last_run_task
    # All modes included — flight/return present with round-trip note
    assert "flight/return" in task
    assert "round-trip price, count once" in task
    assert "flight/one-way" in task
    assert "metro" in task
    # One-way options collapsed to a price range, not listed individually
    assert "$450–$520" in task
    assert "820" in task


def test_budget_wrapper_returns_breakdown_verbatim():
    wrapper, _, _, llm = _make_wrapper()
    llm.chat.return_value = stop_msg(_budget_json(breakdown="Total: $1,200"))
    result = wrapper.execute(query="Tokyo 3 nights", destination="Tokyo", )
    assert result["summary"] == "Total: $1,200"


def test_budget_wrapper_exception_returns_error():
    wrapper, specialist, ks, _ = _make_wrapper()
    specialist.run = MagicMock(side_effect=RuntimeError("LLM unavailable"))
    result = wrapper.execute(query="Tokyo budget", destination="Tokyo", )
    assert result["status"] == "error"
    assert "Tokyo" not in ks.destinations
