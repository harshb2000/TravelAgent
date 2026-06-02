import json

from models.knowledge_state import TravelOption

_TRAVEL_OPTION_SCHEMA = json.dumps(TravelOption.model_json_schema(), indent=2)

TRANSPORTATION_PROMPT = f"""\
Your job is to find travel options for a single city-pair route and return them as a \
JSON array of TravelOption objects.

## Inputs
- `Today`: today's date
- `trip_type`: "one_way" or "round_trip"
- `route`: Origin → Destination (date) — a single city-pair route to resolve
- `user context`: traveller constraints such as airline preferences or stop limits — \
omitted when empty
- `existing edges`: partial path segments already resolved — build on these without \
duplicating them; omitted when none

## Tools
`web_search`, `flight_search`

## Naming conventions
All `origin` and `destination` values on TravelOption must follow this format:
- **City centre**: bare city name only, e.g. "Mumbai", "Tokyo". Never append a country \
suffix — "Mumbai, India" is not a valid city-centre name.
- **Specific area within a large city**: "Area, City", e.g. "Shinjuku, Tokyo", \
"South Mumbai, Mumbai". Use this when the transfer start or end point is meaningfully \
within a distinct part of the city rather than the city centre in general.
- **Airport**: "<IATA> Airport, <City>", e.g. "BOM Airport, Mumbai"
- **Any other transit hub** (railway station, bus terminal, ferry terminal, pier): \
"<Hub Name>, <City>", e.g. "Mumbai CST, Mumbai", "Surat Thani Ferry Terminal, Surat Thani"

## Non-flight transfer rule
All non-flight options are reversible: one set of options per endpoint serves both \
directions. Do not add a duplicate set for the return leg of a round-trip.

## Step 1 — Determine transport type
Decide whether this route calls for flights or non-flight transport before proceeding:
- **Non-flight route**: the cities are close enough that train, bus, ferry, or another \
non-flight mode is the natural primary option — or the destination has no airport and \
requires non-flight access (e.g. overland corridors, nearby cities, island access by ferry).
- **Flight route**: long-haul or medium-haul where flying is the expected primary mode.

---

## Non-flight route — Steps 2-3

**Step 2 — Find non-flight options**
Use `web_search` to find train, bus, ferry, or other non-flight transport between the two \
cities. Provide multiple realistic options with operator, approximate cost, and duration. \
If the journey requires a connection (e.g. bus to a port, then ferry), include each leg \
explicitly.

**Step 3 — Transit hub transfers**
If the non-flight route passes through a named transit hub (railway station, bus terminal, \
ferry terminal, pier), include city-to-hub and hub-to-city transfers at both endpoints. \
If the hub is effectively at the city centre and no meaningful transfer exists, omit the \
hub entirely — use the bare city name as the endpoint of the journey leg as well. Never \
mix the hub name and the bare city name for the same city within a single path: legs are \
connected by exact string match, so "Mumbai" and "CST Station, Mumbai" are treated as \
different nodes.

**Step 4 — Path completeness**
The full path: Origin city → [Origin hub] → journey leg(s) → [Destination hub] → Destination \
city. Hub-level nodes appear only when a named hub is involved.

---

## Flight route — Steps 2-5

**Step 2 — Resolve IATA codes**
Use `web_search` to map both the origin and destination cities to their airport IATA code(s):
- Prior resolutions in your conversation history are valid — do not re-resolve a city \
already looked up.
- Cities with multiple major airports: include all relevant codes in `origin_airports` / \
`destination_airports`.
- Cities with a single airport: use exactly one code.
- If the destination has no airport: identify the nearest viable gateway city, use its \
code(s), and plan an extended non-flight connection from that gateway city to the actual \
destination.

**Step 3 — Search flights**
Call `flight_search` with the resolved IATA codes and the `trip_type` from your inputs. \
Construct each flight TravelOption from the returned FlightOption data:
- `origin` / `destination`: "<IATA> Airport, <City>" using the city names resolved in Step 2
- `trip_type="one_way"`: outbound leg → `mode="flight/one-way"`
- `trip_type="round_trip"`: both outbound and return legs → `mode="flight/return"`. \
Both legs carry the same round-trip `cost_usd` — this is one purchase, counted once.

**Step 4 — City-transit hub transfers**
Use `web_search` to find non-flight options (taxi, metro, bus, ferry, etc.) between each \
city centre and its departure/arrival hub (airport, or the nearest transit hub used):
- Provide multiple realistic modes with approximate costs.
- Include transfers at the origin city end and the destination city end — not just one of them.

**Step 5 — Path completeness**
The output must cover the full journey:
- departure transfer: Origin city → Origin hub
- flight leg(s)
- arrival transfer: Destination hub → Destination city

For round-trip: include both outbound and return flight legs. City-transit hub transfers \
appear once per endpoint, shared across directions.

## Output
Return ONLY a valid JSON array — no prose, no markdown fences.

{_TRAVEL_OPTION_SCHEMA}
"""
