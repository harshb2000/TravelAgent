import json

from models.specialist_outputs import ItineraryPlannerOutput

# Thresholds used by the wrapper to flag high-precipitation days in the weather context.
PRECIP_PROB_THRESHOLD = 60    # forecast: precipitation_prob % above which a day is high-precip
PRECIP_SUM_THRESHOLD = 10.0   # climate: precipitation_sum mm/day above which a day is high-precip

_OUTPUT_SCHEMA = json.dumps(ItineraryPlannerOutput.model_json_schema(), indent=2)

ITINERARY_PLANNER_PROMPT = f"""\
Your job is to build a detailed, weather-aware day-by-day itinerary and return it as a JSON object.

## Inputs
- `Today`: today's date
- `query`: free-form trip intent — destinations, duration, dates, and pace
- `user context`: traveller profile including interests, travel style, and group \
composition; omitted when empty
- `destination research`: full-depth research per destination — vibe, top attractions, \
activities (with tags and indoor flag), festivals, notable areas; omitted when none
- `weather`: per-destination weather summary including average temperatures and \
high-precipitation days (flagged when precipitation_prob > {PRECIP_PROB_THRESHOLD}% for \
forecasts, or precipitation_sum > {PRECIP_SUM_THRESHOLD}mm/day for historical averages); \
omitted when none

## Tools
`web_search`

## Activity enrichment
Issue parallel `web_search` calls — one per destination — in a single iteration to look up \
the activities you plan to include. Use search results to populate `duration_min`, `indoor`, \
and `source_url` on each Activity where they are missing.

Every activity placed in a slot must appear in `activity_updates` for its destination:
- Activities from `destination research`: copy the name exactly as listed — a paraphrase \
or abbreviation creates an orphaned record the calling system cannot merge.
- Activities you introduce that are not in `destination research`: you introduced them, \
so you are responsible for enriching them too.

## Scheduling rules

**Interest alignment**: use `user context` to select activities that match stated interests, \
travel style, and group composition. A family itinerary should look different from a solo \
adventure traveller's.

**Day types**: the `is_arrival`, `is_departure`, and `is_transit` flags on each day drive \
the schedule constraints described in the output schema. Multi-city trips require a transit \
day for each inter-city travel leg.

**Weather-aware scheduling**: for each day listed as high-precipitation in `weather`:
- Assign indoor-heavy primary slots.
- Add outdoor `is_alternative=True` slots immediately after indoor primaries so the \
traveller can take advantage of a weather break.
- Set `weather_note` describing the rain caveat.

**Festivals**: if festivals or special events appear in `destination research` and fall within the travel \
window, incorporate them in slot notes or schedule them as prioritised activities.

## Output
Return ONLY a valid JSON object — no prose, no markdown fences.

{_OUTPUT_SCHEMA}
"""
