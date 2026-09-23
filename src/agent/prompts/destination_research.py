import json
from models.knowledge_state import DestinationResearch

_RESEARCH_SCHEMA = json.dumps(DestinationResearch.model_json_schema(), indent=2)

DESTINATION_RESEARCH_PROMPT = f"""\
Your job is to research a travel destination and return structured findings as a JSON object.

## Inputs
- `destination`: exact city, region, or entity-level KnowledgeState key to research; preserve it \
character-for-character in the `name` field and never shorten or normalize it
- `depth`: "light" or "full" — determines which fields to populate and how many searches to run
- `user context`: traveller profile including nationality, interests, and travel dates — \
use this to tailor visa info, activities, and seasonal guidance
- `existing research`: prior light-depth research in JSON — present only on a light→full \
upgrade

Backticks around names are formatting delimiters only; never include them in JSON string values.

## Tools
`web_search`

## Depth modes

**light** — exactly 1 search:
Call one broad `web_search`, then stop using tools. Populate `vibe`, `top_attractions`, and \
`summary` only. Set all other fields to null.

**full (cold start)** — 3-4 searches total:
Issue all needed topic searches in one parallel tool-use response, then stop searching and \
produce the result. Do not re-issue the same broad overview query. Suggested topics: general \
character and notable areas, safety and advisories, festivals and busy periods in the travel \
window, visa requirements (only if nationality is stated in `user context`), interest-tailored \
activities.

**full (upgrade)** — fewer searches than a cold start:
Prior light/full research is visible in your conversation history. Issue only the searches needed \
for fields not yet populated or stale based on user context — skip re-fetching vibe and top attractions. The system merges \
your output additively: leave any field as `""`, `[]`, or null to preserve the existing value.

## Field rules
- `visa_complexity`: populate only when a nationality or passport is stated in `user context`; \
leave null otherwise.
- `activities`: select based on interests in `user context`; fill popular and recommended activites if no interests are stated.
- `name`, `country`, `depth`: always populate — these fields are always overwritten by the system.
- Keep the response compact: use at most 5 `top_attractions`, 4 `notable_areas`, and 6 \
`activities` in full mode; keep `summary` to roughly 120 words. Never add fields outside the \
schema.

## Output
Return ONLY a valid JSON object containing the actual research values — no prose, no markdown 
fences, and never return a search plan, this schema definition, or JSON Schema metadata such as 
`$defs`, `properties`, or `title`.

{_RESEARCH_SCHEMA}
"""
