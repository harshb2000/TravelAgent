import json
from models.knowledge_state import DestinationResearch

_RESEARCH_SCHEMA = json.dumps(DestinationResearch.model_json_schema(), indent=2)

DESTINATION_RESEARCH_PROMPT = f"""\
Your job is to research a travel destination and return structured findings as a JSON object.

## Inputs
- `destination`: city or region name to research
- `depth`: "light" or "full" — determines which fields to populate and how many searches to run
- `user context`: traveller profile including nationality, interests, and travel dates — \
use this to tailor visa info, activities, and seasonal guidance
- `existing research`: prior light-depth research in JSON — present only on a light→full \
upgrade

## Tools
`web_search`

## Depth modes

**light** — 1 search:
Populate `vibe`, `top_attractions`, and `summary` only. Set all other fields to null.

**full (cold start)** — 3-4 searches:
Run distinct searches covering different topics — do not re-issue the same broad overview \
query. Suggested topics: general character and notable areas, safety and advisories, \
festivals and busy periods in the travel window, visa requirements (only if nationality is \
stated in `user context`), interest-tailored activities.

**full (upgrade)** — fewer searches than a cold start:
Prior light/full research is visible in your conversation history. Issue only the searches needed \
for fields not yet populated or stale based on user context — skip re-fetching vibe and top attractions. The system merges \
your output additively: leave any field as `""`, `[]`, or null to preserve the existing value.

## Field rules
- `visa_complexity`: populate only when a nationality or passport is stated in `user context`; \
leave null otherwise.
- `activities`: select based on interests in `user context`; fill popular and recommended activites if no interests are stated.
- `name`, `country`, `depth`: always populate — these fields are always overwritten by the system.

## Output
Return ONLY a valid JSON object — no prose, no markdown fences.

{_RESEARCH_SCHEMA}
"""
