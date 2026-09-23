import json

from models.specialist_outputs import ItineraryPlannerOutput

# Thresholds used by the wrapper to flag high-precipitation days in the weather context.
PRECIP_PROB_THRESHOLD = 60    # forecast: precipitation_prob % above which a day is high-precip
PRECIP_SUM_THRESHOLD = 10.0   # climate: precipitation_sum mm/day above which a day is high-precip

_OUTPUT_SCHEMA = json.dumps(ItineraryPlannerOutput.model_json_schema(), indent=2)

ITINERARY_PLANNER_PROMPT = f"""\
Your job is to build a detailed day-by-day itinerary and return it as a JSON object.

## Inputs
- `Today`: today's date
- `query`: free-form trip intent — destinations, duration, dates, and pace
- `user context`: traveller profile including interests, travel style, and group \
composition; omitted when empty
- `destination research`: full-depth research per destination — each leading destination label \
is the exact entity-level key supplied to `itinerary_planner`; preserve it character-for-character \
when populating `Itinerary.destinations` and `activity_updates` keys. Includes vibe, top \
attractions, activities (with tags and indoor flag), festivals, and notable areas; omitted when none
- `weather`: per-destination weather summary; its leading destination label is also an exact \
KnowledgeState key — copy it verbatim when referring to that destination. Includes average \
temperatures and high-precipitation days (flagged when precipitation_prob > {PRECIP_PROB_THRESHOLD}% for \
forecasts, or precipitation_sum > {PRECIP_SUM_THRESHOLD}mm/day for historical averages); \
omitted when none

## Tools
`web_search`

## Destination key rule
Destination labels are identifiers, not aliases. Copy them exactly, including country or other \
qualifiers; never shorten `Tokyo, Japan` to `Tokyo` or add a qualifier. The same exact strings \
must be used in `Itinerary.destinations` and as the keys of `activity_updates`. Backticks \
are formatting delimiters only; never include them in JSON values.

## Activity enrichment
Issue exactly one `web_search` call per destination, all in one parallel iteration. Use a \
broad query covering the activities you plan to include; do not issue one search per activity \
or additional search rounds. Use the results to populate `duration_min`, `indoor`, and \
`source_url` on each Activity where they are missing.

Every activity placed in a slot must appear in `activity_updates` for its destination:
- Activities from `destination research`: copy the name exactly as listed — a paraphrase \
or abbreviation creates an orphaned record the calling system cannot merge.
- Activities you introduce that are not in `destination research`: you introduced them, \
so you are responsible for enriching them too.

## Scheduling rules

**Day structure**: arrival day must be light with at most 2 orientation slots; departure day \
may contain morning slots only; every inter-city move needs a transit day whose slots describe \
the journey rather than sightseeing.

**Interest alignment**: use `user context` to select activities that match stated interests, \
travel style, and group composition. A family itinerary should look different from a solo \
adventure traveller's.

**Day types**: the `is_arrival`, `is_departure`, and `is_transit` flags on each day drive \
the schedule constraints described in the output schema. Multi-city trips require a transit \
day for each inter-city travel leg.

**Weather-aware scheduling**: if `weather` is absent, skip this section entirely — do not \
add weather notes or bias toward indoor scheduling. If present, for each day listed as \
high-precipitation:
- Assign indoor-heavy primary slots.
- Add outdoor `is_alternative=True` slots immediately after indoor primaries so the \
traveller can take advantage of a weather break.
- Set `weather_note` describing the rain caveat.

**Festivals**: if festivals or special events appear in `destination research` and fall within the travel \
window, incorporate them in slot notes or schedule them as prioritised activities.

## Output
Return ONLY a valid JSON object containing the actual itinerary values — no prose, no markdown 
fences, and never return this schema definition or JSON Schema metadata such as `$defs`, 
`properties`, or `title`. Keep the itinerary compact: no more than 3 primary slots per day 
and no more than 3 alternative slots per day. Before returning, verify every scheduled 
activity has an exact-name entry in `activity_updates` with enrichment, and that arrival, 
departure, transit, and weather flags obey the rules above.

{_OUTPUT_SCHEMA}
"""
