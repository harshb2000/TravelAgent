import pytest
from models.knowledge_state import (
    DateRange,
    RouteKey,
    DestinationCandidate,
    Activity,
    DestinationResearch,
    StringWithAttribution,
    CostWithAttribution,
    DestinationBudget,
    TravelOption,
    TimeSlot,
    ItineraryDay,
    Itinerary,
    KnowledgeState,
    UserContext,
)
from models.weather import WeatherOutput, DailyWeather


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candidate(name: str, turn: int = 0, query: str = "beach trip") -> DestinationCandidate:
    c = DestinationCandidate(
        name=name,
        country="TestCountry",
        vibe_tags=["beach"],
        rationale=f"Beautiful {name}",
        source_url="http://example.com",
        query=query,
    )
    c.added_at = turn
    return c


def _weather(mode="forecast") -> WeatherOutput:
    return WeatherOutput(
        mode=mode,
        city="Tokyo",
        days=[
            DailyWeather(
                date="2026-06-20",
                temp_max=28.0,
                temp_min=20.0,
                precipitation_prob=10 if mode == "forecast" else None,
                precipitation_sum=None if mode == "forecast" else 2.5,
                weather_description="Sunny" if mode == "forecast" else "",
            )
        ],
    )


# ---------------------------------------------------------------------------
# DateRange.from_string
# ---------------------------------------------------------------------------

def test_date_range_from_string_iso_range():
    dr = DateRange.from_string("2026-06-20 to 2026-06-30")
    assert dr.label == "2026-06-20 to 2026-06-30"
    assert dr.start_date == "2026-06-20"
    assert dr.end_date == "2026-06-30"


def test_date_range_from_string_single_date():
    dr = DateRange.from_string("2026-06-20")
    assert dr.start_date == "2026-06-20"
    assert dr.end_date is None


def test_date_range_from_string_natural_language():
    dr = DateRange.from_string("late June 2026")
    assert dr.label == "late June 2026"
    assert dr.start_date is None
    assert dr.end_date is None


# ---------------------------------------------------------------------------
# KnowledgeState.add_candidates
# ---------------------------------------------------------------------------

def test_add_candidates_appends_never_replaces():
    ks = KnowledgeState()
    ks.add_candidates([_candidate("Tokyo", turn=1)])
    ks.add_candidates([_candidate("Bangkok", turn=2)])
    assert len(ks.candidates) == 2
    assert ks.candidates[0].name == "Tokyo"
    assert ks.candidates[1].name == "Bangkok"


def test_add_candidates_accumulates_across_calls():
    ks = KnowledgeState()
    for i in range(5):
        ks.add_candidates([_candidate(f"City{i}", turn=i)])
    assert len(ks.candidates) == 5


# ---------------------------------------------------------------------------
# KnowledgeState.to_prompt_context — candidate scoring
# ---------------------------------------------------------------------------

def test_to_prompt_context_respects_top_n():
    ks = KnowledgeState()
    for i in range(7):
        ks.add_candidates([_candidate(f"City{i}", turn=i)])
    uc = UserContext("beach holiday")
    result = ks.to_prompt_context(uc, top_n=3)
    # Count city names in result — should be at most 3
    shown = sum(1 for i in range(7) if f"City{i}" in result)
    assert shown <= 3


def test_to_prompt_context_shows_count_when_over_top_n():
    ks = KnowledgeState()
    for i in range(7):
        ks.add_candidates([_candidate(f"City{i}", turn=i)])
    uc = UserContext("beach holiday")
    result = ks.to_prompt_context(uc, top_n=5)
    assert "5 of 7" in result or "showing 5 of 7" in result


def test_to_prompt_context_jaccard_winner_shown_with_top_n_1():
    """With top_n=1 and equal recency, only the Jaccard-winning candidate appears."""
    ks = KnowledgeState()
    # Both candidates added at the same turn → recency is equal, Jaccard alone decides.
    beach = DestinationCandidate(
        name="BeachIsland", country="A", vibe_tags=["beach", "relaxation"],
        rationale="beach resort paradise", source_url="http://ex.com",
        query="beach relaxation holiday",
    )
    beach.added_at = 1
    city = DestinationCandidate(
        name="CityHub", country="B", vibe_tags=["city", "culture"],
        rationale="vibrant city culture scene", source_url="http://ex.com",
        query="city culture exploration",
    )
    city.added_at = 1
    ks.add_candidates([beach, city])
    # "city culture" matches CityHub's tags/rationale/query; BeachIsland shares nothing.
    uc = UserContext("city culture exploration")
    result = ks.to_prompt_context(uc, top_n=1)
    assert "CityHub" in result
    assert "BeachIsland" not in result


def test_to_prompt_context_recency_winner_shown_with_top_n_1():
    """With top_n=1 and equal Jaccard, the more recent candidate appears."""
    ks = KnowledgeState()
    # Both candidates share the same query words → Jaccard is tied; recency decides.
    older = DestinationCandidate(
        name="OlderCity", country="A", vibe_tags=["city"],
        rationale="city trip", source_url="http://ex.com",
        query="city trip",
    )
    older.added_at = 1
    newer = DestinationCandidate(
        name="NewerCity", country="B", vibe_tags=["city"],
        rationale="city trip", source_url="http://ex.com",
        query="city trip",
    )
    newer.added_at = 10
    ks.add_candidates([older, newer])
    uc = UserContext("city trip")
    result = ks.to_prompt_context(uc, top_n=1)
    assert "NewerCity" in result
    assert "OlderCity" not in result


# ---------------------------------------------------------------------------
# KnowledgeState update methods
# ---------------------------------------------------------------------------

def test_update_research_populates_destination():
    ks = KnowledgeState()
    research = DestinationResearch(name="Tokyo", country="Japan", depth="light", summary="Great city")
    ks.update_research("Tokyo", research)
    assert ks.destinations["Tokyo"].research is not None
    assert ks.destinations["Tokyo"].research.summary == "Great city"


def test_update_research_overwrites_existing():
    ks = KnowledgeState()
    ks.update_research("Tokyo", DestinationResearch(name="Tokyo", country="Japan", depth="light", summary="V1"))
    ks.update_research("Tokyo", DestinationResearch(name="Tokyo", country="Japan", depth="full", summary="V2"))
    assert ks.destinations["Tokyo"].research.depth == "full"
    assert ks.destinations["Tokyo"].research.summary == "V2"


def test_update_weather_keyed_by_date_range():
    ks = KnowledgeState()
    dr = DateRange.from_string("2026-06-20 to 2026-06-30")
    wo = _weather()
    ks.update_weather("Tokyo", dr, wo)
    assert ks.destinations["Tokyo"].weather[dr] is wo


def test_update_weather_different_date_ranges_coexist():
    ks = KnowledgeState()
    dr1 = DateRange.from_string("2026-06-20 to 2026-06-30")
    dr2 = DateRange.from_string("2026-07-01 to 2026-07-10")
    ks.update_weather("Tokyo", dr1, _weather("forecast"))
    ks.update_weather("Tokyo", dr2, _weather("climate"))
    assert len(ks.destinations["Tokyo"].weather) == 2


def test_update_route_populates_route_knowledge():
    ks = KnowledgeState()
    dr = DateRange.from_string("2026-07-13")
    option = TravelOption(mode="flight/one-way", origin="Mumbai", destination="Tokyo", cost_usd=300.0)
    ks.update_route("Mumbai", "Tokyo", dr, [option])
    rk = RouteKey("Mumbai", "Tokyo")
    assert rk in ks.routes
    assert ks.routes[rk].options[dr][0].cost_usd == 300.0


def test_update_route_overwrites_same_key():
    ks = KnowledgeState()
    dr = DateRange.from_string("2026-07-13")
    ks.update_route("Mumbai", "Tokyo", dr, [TravelOption(mode="flight/one-way", origin="Mumbai", destination="Tokyo", cost_usd=300.0)])
    ks.update_route("Mumbai", "Tokyo", dr, [TravelOption(mode="flight/one-way", origin="Mumbai", destination="Tokyo", cost_usd=250.0)])
    rk = RouteKey("Mumbai", "Tokyo")
    assert ks.routes[rk].options[dr][0].cost_usd == 250.0


def test_update_destination_budget_populates():
    ks = KnowledgeState()
    budget = DestinationBudget(
        accommodation={"hostel": CostWithAttribution(amount=20.0)},
        food={"street food": CostWithAttribution(amount=5.0)},
        summary="Budget city",
    )
    ks.update_destination_budget("Bangkok", budget)
    assert ks.destinations["Bangkok"].budget is not None
    assert ks.destinations["Bangkok"].budget.summary == "Budget city"


def test_update_destination_budget_merges_categories():
    """Second call adds new keys and overwrites stale ones; unrelated keys are preserved."""
    ks = KnowledgeState()
    ks.update_destination_budget("Bangkok", DestinationBudget(
        accommodation={"hostel": CostWithAttribution(amount=15.0)},
        food={"street food": CostWithAttribution(amount=5.0)},
        summary="First pass",
    ))
    ks.update_destination_budget("Bangkok", DestinationBudget(
        accommodation={"mid-range hotel": CostWithAttribution(amount=60.0)},
        local_transport={"metro": CostWithAttribution(amount=3.0)},
        summary="Second pass",
    ))
    b = ks.destinations["Bangkok"].budget
    # First-call accommodation key preserved alongside new key
    assert "hostel" in b.accommodation
    assert "mid-range hotel" in b.accommodation
    # First-call food preserved (second call had no food data)
    assert "street food" in b.food
    # Second-call transport added (first call had none)
    assert "metro" in b.local_transport
    # Summary updated to latest non-empty value
    assert b.summary == "Second pass"


def test_update_activities_sets_on_research():
    ks = KnowledgeState()
    ks.update_research("Tokyo", DestinationResearch(name="Tokyo", country="Japan", depth="full", summary="x"))
    acts = [Activity(name="Shibuya Crossing", tags=["cultural"], indoor=False)]
    ks.update_activities("Tokyo", acts)
    assert ks.destinations["Tokyo"].research.activities is not None
    assert ks.destinations["Tokyo"].research.activities[0].name == "Shibuya Crossing"


def test_update_activities_merges_by_name():
    """DestinationResearch sets names/tags; ItineraryPlanner enriches duration/indoor — neither overwrites the other."""
    ks = KnowledgeState()
    ks.update_research("Tokyo", DestinationResearch(name="Tokyo", country="Japan", depth="full", summary="x"))

    # First call: DestinationResearchSpecialist — names and tags
    ks.update_activities("Tokyo", [
        Activity(name="Senso-ji Temple", tags=["cultural", "historic"]),
        Activity(name="Shibuya Crossing", tags=["iconic"]),
    ])

    # Second call: ItineraryPlannerSpecialist — enriches with indoor + duration, adds new entry
    ks.update_activities("Tokyo", [
        Activity(name="Senso-ji Temple", tags=["cultural", "historic"], indoor=False, duration_min=90),
        Activity(name="Teamlab Planets", tags=["art", "indoor"], indoor=True, duration_min=120),
    ])

    acts = {a.name: a for a in ks.destinations["Tokyo"].research.activities}

    # Existing entry enriched, not duplicated
    assert len(acts) == 3
    assert acts["Senso-ji Temple"].duration_min == 90
    assert acts["Senso-ji Temple"].indoor is False
    assert "cultural" in acts["Senso-ji Temple"].tags

    # Entry from first call with no second-call counterpart is preserved as-is
    assert "Shibuya Crossing" in acts

    # New entry from second call appended
    assert "Teamlab Planets" in acts
    assert acts["Teamlab Planets"].indoor is True


def test_update_itinerary_stored_by_frozenset():
    ks = KnowledgeState()
    itin = Itinerary(destinations=["Tokyo"], start_date="2026-06-20", days=[])
    ks.update_itinerary(frozenset(["Tokyo"]), itin)
    assert frozenset(["Tokyo"]) in ks.itineraries
    assert ks.itineraries[frozenset(["Tokyo"])] is itin


def test_update_itinerary_overwrites_same_destination_set():
    ks = KnowledgeState()
    itin1 = Itinerary(destinations=["Tokyo"], days=[])
    itin2 = Itinerary(destinations=["Tokyo"], start_date="2026-07-01", days=[])
    ks.update_itinerary(frozenset(["Tokyo"]), itin1)
    ks.update_itinerary(frozenset(["Tokyo"]), itin2)
    assert ks.itineraries[frozenset(["Tokyo"])].start_date == "2026-07-01"


# ---------------------------------------------------------------------------
# UserContext — wordset
# ---------------------------------------------------------------------------

def test_user_context_wordset_updates_on_context_change():
    uc = UserContext()
    uc.context = "I want to visit Tokyo in June for food"
    assert "tokyo" in uc.wordset


def test_user_context_wordset_unchanged_without_context_reassignment():
    uc = UserContext("Tokyo trip")
    ws_before = uc.wordset
    _ = uc.wordset  # read again — must not trigger recompute
    assert uc.wordset is ws_before


def test_user_context_wordset_recomputed_on_second_assignment():
    uc = UserContext("Tokyo")
    assert "tokyo" in uc.wordset
    uc.context = "Bali beach holiday"
    assert "bali" in uc.wordset
    assert "tokyo" not in uc.wordset


# ---------------------------------------------------------------------------
# UserContext — blocklist
# ---------------------------------------------------------------------------

def test_user_context_blocklist_from_not_pattern():
    uc = UserContext("I want beaches but not Thailand")
    assert "thailand" in uc.blocklist


def test_user_context_blocklist_from_avoid_pattern():
    uc = UserContext("avoid crowds")
    # "crowd" or "crowds" (lemmatized) in blocklist
    assert "crowd" in uc.blocklist or "crowds" in uc.blocklist


def test_user_context_blocklist_excluded_from_wordset():
    uc = UserContext("not Thailand, prefer Japan")
    assert "thailand" not in uc.wordset
    assert "japan" in uc.wordset


def test_user_context_blocklist_and_wordset_recomputed_together():
    uc = UserContext("I love Japan")
    assert "thailand" not in uc.blocklist
    uc.context = "I love Japan but not Thailand"
    assert "thailand" in uc.blocklist
    assert "thailand" not in uc.wordset


def test_user_context_initial_context_in_constructor_triggers_recompute():
    uc = UserContext("beach trip to Bali, not Thailand")
    assert "bali" in uc.wordset
    assert "thailand" in uc.blocklist


# ---------------------------------------------------------------------------
# DestinationCandidate should_exclude
# ---------------------------------------------------------------------------

def test_should_exclude_by_name():
    c = DestinationCandidate(name="Thailand", country="Thailand", vibe_tags=["beach"], rationale="x", source_url="", query="")
    assert c.should_exclude(frozenset(["thailand"]))
    assert not c.should_exclude(frozenset(["japan"]))


def test_should_exclude_by_country():
    c = DestinationCandidate(name="Phuket", country="Thailand", vibe_tags=["beach"], rationale="x", source_url="", query="")
    assert c.should_exclude(frozenset(["thailand"]))


def test_should_exclude_tag_only_tag_blocked():
    # Single tag, and it is blocked → blocked(1) > unblocked(0) → exclude
    c = DestinationCandidate(name="Maldives", country="Maldives", vibe_tags=["beach"], rationale="x", source_url="", query="")
    assert c.should_exclude(frozenset(["beach"]))


def test_should_exclude_tag_minority_not_excluded():
    # 1 of 3 tags blocked → Jaccard scoring handles deprioritisation, no hard exclusion
    c = DestinationCandidate(name="Barcelona", country="Spain", vibe_tags=["beach", "city", "culture"], rationale="x", source_url="", query="")
    assert not c.should_exclude(frozenset(["beach"]))


def test_should_exclude_tag_majority_blocked():
    # 2 of 3 tags blocked → blocked(2) > unblocked(1) → exclude
    c = DestinationCandidate(name="Ibiza", country="Spain", vibe_tags=["beach", "nightlife", "food"], rationale="x", source_url="", query="")
    assert c.should_exclude(frozenset(["beach", "nightlife"]))
    assert not c.should_exclude(frozenset(["beach"]))  # 1 vs 2 — kept


def test_should_exclude_tag_tie_not_excluded():
    # Equal blocked and unblocked tags → not strictly greater → keep
    c = DestinationCandidate(name="SomeCity", country="Spain", vibe_tags=["beach", "city"], rationale="x", source_url="", query="")
    assert not c.should_exclude(frozenset(["beach"]))


def test_should_exclude_tag_lemmatised():
    # "beaches" in blocklist → lemmatised to "beach" → matches tag "beach"
    c = DestinationCandidate(name="Bali", country="Indonesia", vibe_tags=["beach"], rationale="x", source_url="", query="")
    assert c.should_exclude(frozenset(["beach"]))   # blocklist already lemmatised by UserContext


def test_should_exclude_multiword_name():
    # "not Czech" → blocklist: {"czech"} — should still block "Czech Republic"
    c = DestinationCandidate(name="Prague", country="Czech Republic", vibe_tags=["city"], rationale="x", source_url="", query="")
    assert c.should_exclude(frozenset(["czech"]))


def test_should_exclude_hyphenated_tag():
    # "not budget" → blocklist: {"budget"} — should block tag "budget-friendly"
    c = DestinationCandidate(name="Bangkok", country="Thailand", vibe_tags=["budget-friendly"], rationale="x", source_url="", query="")
    assert c.should_exclude(frozenset(["budget"]))


def test_should_exclude_empty_blocklist():
    c = DestinationCandidate(name="Tokyo", country="Japan", vibe_tags=["city"], rationale="x", source_url="", query="")
    assert not c.should_exclude(frozenset())


# ---------------------------------------------------------------------------
# DestinationCandidate wordset
# ---------------------------------------------------------------------------

def test_destination_candidate_wordset_populated_from_fields():
    c = DestinationCandidate(
        name="Tokyo",
        country="Japan",
        vibe_tags=["city", "food"],
        rationale="amazing food scene",
        source_url="http://ex.com",
        query="best food cities Asia",
    )
    assert len(c.wordset) > 0
    # "tokyo" or "food" should appear after NLTK processing
    assert "tokyo" in c.wordset and "food" in c.wordset
