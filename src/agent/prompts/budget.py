import json

from models.specialist_outputs import BudgetSpecialistOutput

_OUTPUT_SCHEMA = json.dumps(BudgetSpecialistOutput.model_json_schema(), indent=2)

BUDGET_PROMPT = f"""\
Your job is to produce a detailed trip cost breakdown and return it as a JSON object.

## Inputs
- `Today`: today's date
- `query`: free-form trip configuration — party size, nights, destination, accommodation \
style, and any stated budget
- `user context`: traveller profile including home currency and nationality; omitted when empty
- `existing budget`: JSON with per-category cost data already known for the destination \
(accommodation, food, local transport, activities), all amounts in USD; omitted when none
- `travel costs`: known transport options per route and mode with cost ranges; \
`flight/return` entries are annotated `(round-trip price, count once)`; omitted when none

## Tools
`web_search`, `currency_convert`, `calculate`

## Rules

**Searching**: Issue `web_search` only for cost categories absent from `existing budget` \
(accommodation, food, local transport, activities). Run all needed searches in a single \
iteration — do not serialise independent category searches.

**Currency**: If a home currency is stated in `user context` or `query`, call \
`currency_convert` once to get the USD exchange rate. It is reusable from conversation \
history — do not call it again in the same session.

**Arithmetic**: Use `calculate` for every numeric operation — rate × duration, \
amount × party size, range low/high, subtotals, totals, and USD-to-home-currency \
conversion. Never compute numbers yourself.

**Scaling**:
- Accommodation: per-room/night × nights (scale rooms for party size when needed)
- Food: per-person/day × party size × days
- Activities: per-person × party size

**Travel costs**: Include all options from `travel costs` in the breakdown. \
`flight/return` entries carry a round-trip `cost_usd` shared across both the outbound \
and return legs — count it once, not per leg.

## Output
Return ONLY a valid JSON object — no prose, no markdown fences.

{_OUTPUT_SCHEMA}

The layout below shows the expected breakdown format. It is a structural template — \
do not treat any placeholder value as real data or let it influence cost estimates:

  <Destination> — <N> nights, <P> people (<style>)
    Flights (rt, per person):     $X        [$Y total]
    Accommodation (per room/nt):  $A–B      [$C–D total, N nights]
    Food (per person/day):        $E–F/day  [$G–H total]
    Local transport (per person): $I–J/day  [$K–L total]
    Activities:                   $M–N      [$O–P total, P people]
    ─────────────────────────────────────────────────
    Total (<P> people, USD):      $Q–R
    Total (<CUR>, @<rate>):       <CUR> S–T
    Budget (stated):              <CUR> U/person = <CUR> V total
    Delta:                        <CUR> W–X under budget ✓
"""
