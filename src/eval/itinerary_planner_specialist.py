#!/usr/bin/env python3
"""
Assertion-based evaluation for ItineraryPlannerSpecialist.

Group A: Day structure rules (arrival light, departure morning-only, transit describes journey)
Group B: Weather-aware scheduling (indoor primaries, alternative slot constraints)
Group C: Activity enrichment (searches issued, parallel for multi-dest, activity_updates complete)

Every test makes real LLM and real web search API calls.

Usage (from src/):
    python eval/itinerary_planner_specialist.py [filter ...]

Results saved to:
    src/eval/results/itinerary_planner_specialist/<timestamp>.json
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from clients.llm_client import LLMClient
from clients.search_client import SearchClient
from config.settings import settings
from config.specialist_tuning import resolve_model_config
from models.specialist_outputs import ItineraryPlannerOutput
from specialists.itinerary_planner import ItineraryPlannerSpecialist
from tools.web_search import WebSearchTool


# ---------------------------------------------------------------------------
# Minimal test-data context strings
# ---------------------------------------------------------------------------

_TOKYO_RESEARCH = """\
Tokyo:
  vibe: Sprawling megacity where ancient temples, neon-lit alleys, and world-class \
cuisine coexist.
  top_attractions: Senso-ji Temple, Shibuya Crossing, Tsukiji Outer Market
  activities:
    - Senso-ji Temple (tags: cultural, outdoor; indoor: false)
    - teamLab Planets (tags: art, technology; indoor: true)
    - Ramen Museum Shinjuku (tags: food; indoor: true)
    - Shibuya Crossing walk (tags: urban, outdoor; indoor: false)
    - Tsukiji Outer Market breakfast (tags: food, outdoor; indoor: false)
    - Shinjuku Golden Gai bar-hop (tags: nightlife; indoor: true)
  festivals: Sumida River Fireworks Festival (last Saturday of July)
  notable_areas:
    Asakusa: Historic district centred on Senso-ji; street food and craft shops.
    Shinjuku: Shopping, nightlife, Golden Gai laneway bars.\
"""

_KYOTO_RESEARCH = """\
Kyoto:
  vibe: Japan's ancient capital — classical temples, Shinto shrines, and preserved \
machiya townhouses.
  top_attractions: Fushimi Inari Shrine, Arashiyama Bamboo Grove, Kinkaku-ji
  activities:
    - Fushimi Inari Shrine hike (tags: cultural, outdoor; indoor: false)
    - Arashiyama Bamboo Grove walk (tags: nature, outdoor; indoor: false)
    - Kinkaku-ji Golden Pavilion (tags: cultural, outdoor; indoor: false)
    - Nishiki Market food tour (tags: food; indoor: true)
    - Tea ceremony in Higashiyama (tags: cultural; indoor: true)
    - Gion geisha district evening stroll (tags: cultural, outdoor; indoor: false)
  festivals: Gion Matsuri (all of July — major processions July 17 and 24)
  notable_areas:
    Higashiyama: Preserved street district with Kiyomizu-dera.
    Arashiyama: Bamboo groves, temples, and the Oi River.\
"""

_TOKYO_WEATHER_CLEAR = """\
Tokyo (forecast):
  2026-06-20: temp_max=28, temp_min=22, precipitation_prob=10% — clear
  2026-06-21: temp_max=27, temp_min=21, precipitation_prob=15% — clear
  2026-06-22: temp_max=29, temp_min=23, precipitation_prob=10% — clear
  2026-06-23: temp_max=30, temp_min=24, precipitation_prob=5%  — clear
  2026-06-24: temp_max=28, temp_min=22, precipitation_prob=10% — clear
  2026-06-25: temp_max=27, temp_min=21, precipitation_prob=15% — clear\
"""

_TOKYO_WEATHER_WITH_RAIN = """\
Tokyo (forecast):
  2026-06-20: temp_max=28, temp_min=22, precipitation_prob=10% — clear
  2026-06-21: temp_max=24, temp_min=20, precipitation_prob=80% — HIGH-PRECIP
  2026-06-22: temp_max=27, temp_min=21, precipitation_prob=15% — clear
  2026-06-23: temp_max=30, temp_min=24, precipitation_prob=5%  — clear
  2026-06-24: temp_max=28, temp_min=22, precipitation_prob=10% — clear
  2026-06-25: temp_max=27, temp_min=21, precipitation_prob=15% — clear\
"""


# ---------------------------------------------------------------------------
# Run context
# ---------------------------------------------------------------------------

class _Run:
    def __init__(self):
        self.specialist: ItineraryPlannerSpecialist | None = None
        self.output: ItineraryPlannerOutput | None = None
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


def _make_specialist(llm: LLMClient, search_client: SearchClient) -> ItineraryPlannerSpecialist:
    return ItineraryPlannerSpecialist(llm, [WebSearchTool(search_client)])


def _history_messages(specialist: ItineraryPlannerSpecialist) -> list[dict]:
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


def _primary_slots(day) -> list:
    return [s for s in day.slots if not s.is_alternative]


def _alt_runs(day) -> list[int]:
    """Lengths of consecutive is_alternative=True slot runs within a day."""
    runs, current = [], 0
    for slot in day.slots:
        if slot.is_alternative:
            current += 1
        else:
            if current:
                runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


_EVENING_LABELS = {"evening", "night", "nighttime", "late evening"}
_TIME_CUTOFF = "15:00"


def _is_afternoon_or_later(start_time: str) -> bool:
    t = start_time.lower().strip()
    if t in _EVENING_LABELS:
        return True
    if re.match(r"^\d{2}:\d{2}$", t):
        return t >= _TIME_CUTOFF
    return False


_TRAVEL_TERMS = {
    "flight", "train", "shinkansen", "transfer", "travel",
    "depart", "arrive", "journey", "bullet", "transit", "bus",
}


def _is_travel_activity(name: str) -> bool:
    return any(term in name.lower() for term in _TRAVEL_TERMS)


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


def _serialize_output(output: ItineraryPlannerOutput | None) -> dict | None:
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
# Group A — Day structure rules
# ---------------------------------------------------------------------------

def arrival_day_is_light(llm, search_client, run):
    """Day 1 must be flagged is_arrival=True with at most 2 orientation slots (A1)."""
    run.specialist = _make_specialist(llm, search_client)
    run.output = run.specialist.run(
        query="5 nights Tokyo, arrival June 20",
        destination_research=_TOKYO_RESEARCH,
        weather=_TOKYO_WEATHER_CLEAR,
    )
    days = run.output.itinerary.days
    assert days, "itinerary has no days"
    day1 = days[0]
    assert day1.is_arrival, f"day 1 is not flagged is_arrival (got is_arrival={day1.is_arrival})"
    assert len(day1.slots) <= 2, (
        f"arrival day has {len(day1.slots)} slots — expected ≤ 2 orientation activities"
    )


def departure_day_is_morning_only(llm, search_client, run):
    """Last day must be flagged is_departure=True with no afternoon/evening slots (A2)."""
    run.specialist = _make_specialist(llm, search_client)
    run.output = run.specialist.run(
        query="5 nights Tokyo, arrival June 20, departure June 25",
        destination_research=_TOKYO_RESEARCH,
        weather=_TOKYO_WEATHER_CLEAR,
    )
    days = run.output.itinerary.days
    assert days, "itinerary has no days"
    last_day = days[-1]
    assert last_day.is_departure, (
        f"last day (day {last_day.day_num}) is not flagged is_departure"
    )
    late_slots = [s for s in last_day.slots if _is_afternoon_or_later(s.start_time)]
    run.extras["departure_day_slots"] = [
        {"start_time": s.start_time, "activity": s.activity.name} for s in last_day.slots
    ]
    assert not late_slots, (
        f"departure day has afternoon/evening slots: "
        f"{[(s.start_time, s.activity.name) for s in late_slots]}"
    )


def transit_day_describes_journey_not_sightseeing(llm, search_client, run):
    """Multi-city trip must include a transit day whose slots describe the journey leg (A3)."""
    run.specialist = _make_specialist(llm, search_client)
    run.output = run.specialist.run(
        query="10 nights total: 5 Tokyo then 5 Kyoto, arrival June 20",
        destination_research=f"{_TOKYO_RESEARCH}\n\n{_KYOTO_RESEARCH}",
        weather=_TOKYO_WEATHER_CLEAR,
    )
    days = run.output.itinerary.days
    transit_days = [d for d in days if d.is_transit]
    run.extras["transit_days"] = [
        {"day_num": d.day_num, "slots": [s.activity.name for s in d.slots]}
        for d in transit_days
    ]
    assert transit_days, "no transit day found — expected one inter-city travel day"
    transit_day = transit_days[0]
    has_travel_slot = any(_is_travel_activity(s.activity.name) for s in transit_day.slots)
    assert has_travel_slot, (
        f"transit day {transit_day.day_num} has no travel-related slot. "
        f"Slots: {[s.activity.name for s in transit_day.slots]}"
    )


# ---------------------------------------------------------------------------
# Group B — Weather-aware scheduling
# ---------------------------------------------------------------------------

def high_precip_day_has_indoor_primary_slots(llm, search_client, run):
    """Days with weather_note set must have at least one indoor primary slot (B1).

    June 21 is flagged HIGH-PRECIP (precipitation_prob=80%) in the weather context.
    The LLM must set weather_note on that day and assign indoor-heavy primaries.
    """
    run.specialist = _make_specialist(llm, search_client)
    run.output = run.specialist.run(
        query="5 nights Tokyo, arrival June 20",
        destination_research=_TOKYO_RESEARCH,
        weather=_TOKYO_WEATHER_WITH_RAIN,
    )
    days = run.output.itinerary.days
    rainy_days = [d for d in days if d.weather_note]
    run.extras["rainy_days"] = [
        {
            "day_num": d.day_num,
            "weather_note": d.weather_note,
            "primary_slots": [
                {"activity": s.activity.name, "indoor": s.activity.indoor}
                for s in _primary_slots(d)
            ],
        }
        for d in rainy_days
    ]
    assert rainy_days, (
        "no day has weather_note set — LLM may have ignored the HIGH-PRECIP flag"
    )
    for day in rainy_days:
        primaries = _primary_slots(day)
        has_indoor = any(s.activity.indoor for s in primaries)
        assert has_indoor, (
            f"day {day.day_num} has weather_note but no indoor primary slot. "
            f"Primary activities: {[(s.activity.name, s.activity.indoor) for s in primaries]}"
        )


def alternative_slot_never_starts_a_day(llm, search_client, run):
    """The first slot of every day must not be an alternative (B2)."""
    run.specialist = _make_specialist(llm, search_client)
    run.output = run.specialist.run(
        query="5 nights Tokyo, arrival June 20",
        destination_research=_TOKYO_RESEARCH,
        weather=_TOKYO_WEATHER_WITH_RAIN,
    )
    violations = [
        d.day_num for d in run.output.itinerary.days
        if d.slots and d.slots[0].is_alternative
    ]
    assert not violations, (
        f"alternative slot starts day(s): {violations} — "
        f"an alternative has no primary to be contingent on if it leads the day"
    )


def at_most_two_alternatives_per_primary_slot(llm, search_client, run):
    """No run of consecutive alternative slots may exceed 2 (B3)."""
    run.specialist = _make_specialist(llm, search_client)
    run.output = run.specialist.run(
        query="5 nights Tokyo, arrival June 20",
        destination_research=_TOKYO_RESEARCH,
        weather=_TOKYO_WEATHER_WITH_RAIN,
    )
    violations = []
    for day in run.output.itinerary.days:
        for run_len in _alt_runs(day):
            if run_len > 2:
                violations.append(f"day {day.day_num}: run of {run_len} consecutive alternatives")
    assert not violations, f"alternative runs exceed 2: {violations}"


def at_most_three_alternatives_per_day(llm, search_client, run):
    """Total alternative slots per day must not exceed 3 (B4)."""
    run.specialist = _make_specialist(llm, search_client)
    run.output = run.specialist.run(
        query="5 nights Tokyo, arrival June 20",
        destination_research=_TOKYO_RESEARCH,
        weather=_TOKYO_WEATHER_WITH_RAIN,
    )
    violations = []
    for day in run.output.itinerary.days:
        count = sum(1 for s in day.slots if s.is_alternative)
        if count > 3:
            violations.append(f"day {day.day_num}: {count} alternative slots")
    assert not violations, f"days exceed 3 alternative slots: {violations}"


# ---------------------------------------------------------------------------
# Group C — Activity enrichment
# ---------------------------------------------------------------------------

def at_least_one_enrichment_search_issued(llm, search_client, run):
    """At least one web_search must be issued — activity fields must come from search (C1)."""
    run.specialist = _make_specialist(llm, search_client)
    run.output = run.specialist.run(
        query="5 nights Tokyo, arrival June 20",
        destination_research=_TOKYO_RESEARCH,
        weather=_TOKYO_WEATHER_CLEAR,
    )
    msgs = _history_messages(run.specialist)
    searches = _get_tool_calls(msgs, "web_search")
    assert searches, "no web_search calls found — activity enrichment may be hallucinated"


def multi_destination_enrichment_uses_parallel_searches(llm, search_client, run):
    """Multi-destination trips must issue parallel web_search calls in a single iteration (C2)."""
    run.specialist = _make_specialist(llm, search_client)
    run.output = run.specialist.run(
        query="10 nights total: 5 Tokyo then 5 Kyoto, arrival June 20",
        destination_research=f"{_TOKYO_RESEARCH}\n\n{_KYOTO_RESEARCH}",
        weather=_TOKYO_WEATHER_CLEAR,
    )
    msgs = _history_messages(run.specialist)
    parallel_found = any(
        sum(1 for tc in msg["tool_calls"] if tc["function"]["name"] == "web_search") > 1
        for msg in msgs
        if msg.get("role") == "assistant" and msg.get("tool_calls")
    )
    all_queries = [_parse_args(tc).get("query", "") for tc in _get_tool_calls(msgs, "web_search")]
    run.extras["web_search_queries"] = all_queries
    assert parallel_found, (
        f"no iteration had parallel web_search calls for a 2-destination trip — "
        f"enrichment appears serialised. Queries: {all_queries}"
    )


def every_itinerary_activity_has_activity_updates_entry(llm, search_client, run):
    """Every slot activity (non-transit) must appear in activity_updates with enrichment (C3).

    Covers two sub-cases:
    - Known activity (from destination research): name must match exactly.
    - New activity introduced by the planner: must still have an entry.
    In both cases, duration_min or source_url must be populated (not just name echoed back).
    """
    run.specialist = _make_specialist(llm, search_client)
    run.output = run.specialist.run(
        query="5 nights Tokyo, arrival June 20",
        destination_research=_TOKYO_RESEARCH,
        weather=_TOKYO_WEATHER_CLEAR,
    )
    itinerary = run.output.itinerary
    activity_updates = run.output.activity_updates

    missing_entry: list[str] = []
    missing_enrichment: list[str] = []

    for day in itinerary.days:
        if day.is_transit:
            continue
        dest = day.location
        updates_by_name = {a.name: a for a in activity_updates.get(dest, [])}
        for slot in day.slots:
            name = slot.activity.name
            if name not in updates_by_name:
                missing_entry.append(f"day {day.day_num} [{dest}]: '{name}'")
            else:
                a = updates_by_name[name]
                if a.duration_min is None and not a.source_url:
                    missing_enrichment.append(f"day {day.day_num} [{dest}]: '{name}' has no duration_min or source_url")

    run.extras["missing_activity_updates_entry"] = missing_entry
    run.extras["missing_enrichment"] = missing_enrichment

    assert not missing_entry, (
        f"activities in slots with no activity_updates entry: {missing_entry}"
    )
    assert not missing_enrichment, (
        f"activity_updates entries with no enrichment (duration_min and source_url both absent): "
        f"{missing_enrichment}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import datetime as dt

    llm = _make_llm()
    search_client = SearchClient(api_key=settings.tavily_api_key)

    all_tests = [
        arrival_day_is_light,
        departure_day_is_morning_only,
        transit_day_describes_journey_not_sightseeing,
        high_precip_day_has_indoor_primary_slots,
        alternative_slot_never_starts_a_day,
        at_most_two_alternatives_per_primary_slot,
        at_most_three_alternatives_per_day,
        at_least_one_enrichment_search_issued,
        multi_destination_enrichment_uses_parallel_searches,
        every_itinerary_activity_has_activity_updates_entry,
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
        "specialist": "ItineraryPlannerSpecialist",
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model": settings.llm_model,
        "results": results,
        "summary": {"passed": passed, "failed": total - passed, "total": total},
    }

    results_dir = Path(__file__).parent / "results" / "itinerary_planner_specialist"
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = results_dir / f"{ts}.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
