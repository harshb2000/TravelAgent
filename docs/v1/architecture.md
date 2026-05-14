# Technical Architecture v1

Read `philosophy.md` first for the reasoning behind the decisions here.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  CLI (main.py)                                                       │
│  loop: user_input → Orchestrator.turn(input) → print(response)      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Orchestrator                                                        │
│                                                                      │
│  State: UserContext, KnowledgeState, ConversationHistory         │
│                                                                      │
│  Per turn:                                                           │
│    1. Update UserContext from user message                           │
│    2. ReAct loop: call specialists via tool use until ready to reply │
│       Multiple tool_calls in one response → parallel execution       │
│    3. Update KnowledgeState from specialist results                  │
│    4. Return final response                                          │
└──────┬──────────┬──────────┬──────────┬───────────┬─────────────────┘
       │          │          │          │           │
       ▼          ▼          ▼          ▼           ▼
  Explorer  Destination  Transport  Weather    Budget
  Agent     Research     Agent      Agent      Agent
            Agent
                                               ▼
                                          Itinerary
                                          Planner
                                          Agent
                                               ▼
                                          Artifact
                                          Agent
```

Each specialist runs with its own system prompt and tool set. Raw API data never enters the Orchestrator's context — only structured summaries come back.

---

## Data Models

### UserContext

The Orchestrator maintains a **free-text context string** that accumulates and updates as the conversation progresses. This string is passed to specialists that need it.

```
context: str   # running natural language summary of who is travelling,
               # from where, what they want, constraints, and anything else relevant.
               # Appended to or corrected by the Orchestrator each turn. Never reset.
```

**Why free text, not a schema:**
A fixed schema encodes assumptions about what a trip looks like. It handles "solo traveler from Mumbai, mid-range budget" but breaks for "2 people from Delhi and 2 from Mumbai", "I'm already in Bangkok", "my partner hates beaches but I love them", or "elderly parents, need slow pace". Free text handles all of these naturally — each specialist's LLM reads it and extracts what it needs for the task at hand.

**Example of context evolving across turns:**

```
# Turn 1 — "we want to find a beach destination, 4 of us"
context = "Group of 4 looking for a beach destination. No other details yet."

# Turn 2 — "2 from Delhi, 2 from Mumbai, budget ₹40–50k per person, late June"
context = "Group of 4: 2 flying from Delhi, 2 from Mumbai, meeting at a beach
           destination. Budget ₹40k–50k per person. Late June. Open to international."

# Turn 3 — "preferably not too touristy, one of us is vegan"
context = "Group of 4: 2 flying from Delhi, 2 from Mumbai, meeting at a beach
           destination. Budget ₹40k–50k per person. Late June. Open to international.
           Prefer less touristy spots. One person is vegan."
```

**Structured hints — extracted on demand, not tracked as schema fields:**
A few values need a specific format for API calls (exact dates for Amadeus, ISO currency code for Frankfurter). These are extracted from the context string by the Orchestrator when a specialist needs them — not maintained as persistent typed fields:

| Hint | Extracted for | Example |
|---|---|---|
| `date_range` | WeatherAgent, TransportationAgent | "June 20–30 2026" |
| `budget_range` | BudgetAgent | "₹40,000–₹50,000 per person" |
| `home_currency` | BudgetAgent | "INR" |
| `nationality` | DestinationResearchAgent (visa) | "Indian" |

The `date_range` hint is also what the Orchestrator passes as an argument when calling time-sensitive specialist tools (`weather_agent(destination, date_range=...)`, `flight_search(origin, destination, date_range=...)`). The wrapper tool constructs the typed `DateRange` object from this string and uses it as the KnowledgeState key.

If a hint is not present and is needed, the Orchestrator either asks a clarifying question or makes a stated assumption before dispatching — with one exception: for light-depth destination comparisons, dates are not required. The Orchestrator passes `date_range="next few months"` and the specialist uses climate mode. This assumption is stated in the response ("I'm looking at typical conditions for the coming months"). Queries where timing is irrelevant (safety, visa requirements, general research) do not receive a date_range argument at all.

**Origin city is not a required field and never a session gate.** It is part of the free-text context and may be absent, single-valued, or multi-valued ("2 from Delhi, 2 from Mumbai"). TransportationAgent receives the full context string and determines what flight legs to search based on it.

### KnowledgeState

What has been learned about each destination or option during the session.

```
destinations: dict[str, DestinationKnowledge]

DateRange:
  label:      str           # canonical key: "June 2026", "late June", "2026-06-20 to 2026-06-30"
  start_date: str | None    # ISO date when specific; None for vague ranges ("late June", "autumn")
  end_date:   str | None    # ISO date when specific; None for vague ranges

  # Constructor used by wrapper tools — LLM only ever passes a plain string
  from_string(s: str) -> DateRange
    parses "YYYY-MM-DD to YYYY-MM-DD" → populates start_date + end_date
    parses "YYYY-MM-DD"               → populates start_date only
    otherwise                         → label-only (start_date=None, end_date=None)

DestinationKnowledge:
  name:        str
  country:     str
  research:    DestinationResearch | None
  weather:     dict[DateRange, WeatherSummary]       # keyed by queried window; grows as user asks about different dates
  flights:     dict[DateRange, list[FlightDetails]]  # keyed by departure window; grows as user explores different dates/routes
  budget:      BudgetBreakdown | None
  depth:       "light" | "full"
```

`weather` and `flights` start empty and accumulate across turns. If the user asks "what about November instead?", a new `DateRange("November 2026")` entry is added rather than overwriting the June data already gathered.

**DateRange construction and defaults:** The Orchestrator LLM passes `date_range` as a **plain string** in the tool call args — the tool schema exposes it as `{"type": "string"}`. The wrapper tool constructs the typed `DateRange` via `DateRange.from_string(s)`, a classmethod that attempts to parse ISO date patterns (`"2026-06-20 to 2026-06-30"`) and falls back to a label-only instance for natural language strings (`"late June 2026"`, `"next few months"`). The LLM never constructs or knows about the `DateRange` schema. Three cases:

| Scenario | Orchestrator passes | DateRange produced | Specialist mode |
|---|---|---|---|
| Specific dates known ("June 20–30") | `"2026-06-20 to 2026-06-30"` | `label=..., start_date="2026-06-20", end_date="2026-06-30"` | Forecast if ≤16 days out, else climate |
| Vague timing ("late June", "autumn") | `"late June 2026"` | `label="late June 2026", start_date=None, end_date=None` | Climate mode |
| No dates, light-depth comparison | `"next few months"` | `label="next few months", start_date=None, end_date=None` | Climate mode; assumption stated to user |
| No dates, full-depth / itinerary | — | Orchestrator asks first; does not dispatch until answered | — |
| Timing irrelevant (visa, safety) | *(arg omitted)* | No DateRange created; KnowledgeState not keyed by date | — |

**KnowledgeState ownership:** The Orchestrator's Python code owns all writes — the LLM never updates KnowledgeState directly. Each specialist is registered on the Orchestrator as a wrapper tool whose `execute()` method: (1) calls the specialist, (2) merges the typed result into KnowledgeState via typed update methods, (3) returns a plain-text summary to the LLM. `KnowledgeState` exposes:

```
update_research(destination: str, result: DestinationResearch) → None
update_weather(destination: str, date_range: DateRange, result: WeatherSummary) → None
update_flights(destination: str, date_range: DateRange, results: list[FlightDetails]) → None
update_budget(destination: str, result: BudgetBreakdown) → None
```

Raw specialist output (typed Pydantic models) never enters the LLM's context — only the summary string returned by the wrapper does.

---

## Orchestrator Decision Logic

Each turn runs through the following decision tree before any specialist is called:

```
1. Can this be answered from existing KnowledgeState?
   YES → synthesise response, no specialist calls
    NO → continue

2. Is the query too ambiguous to act on usefully?
   Ambiguity criteria:
     - Intent unclear (multiple conflicting interpretations)
     - No origin context at all AND the query would produce meaningfully better results
       with it (e.g. "where can I surf?" benefits from knowing the region; ExplorerAgent
       can still run globally, but asking "roughly where are you based?" first is cheap
       and produces a far more relevant shortlist)
     - Asking one targeted question would unlock significantly better results
   YES → respond with 1–2 clarifying questions (batch them)
    NO → continue

3. Does this require specialist calls?
   Evaluate cheapest sufficient path:
     - Single specialist? → one tool call
     - Multiple specialists at once? → multiple tool_calls in one response (run in parallel)
     - Results not yet sufficient? → ReAct loop continues with further specialist calls
```

**Clarification cap:** The Orchestrator asks at most one clarification round per user message. If the user gives a vague answer to a clarifying question, the Orchestrator makes a reasonable stated assumption and proceeds rather than asking again.

**Depth escalation triggers — when the Orchestrator upgrades a destination from `depth="light"` to `depth="full"`:**
1. User names a destination directly (not from a shortlist) — full depth from the start, no shortlisting
2. User selects or explicitly engages with a destination from a shortlist
3. User asks a question about a place that light research doesn't cover (daily costs, safety, neighbourhoods, specific visa requirements)
4. ItineraryPlannerAgent is being called — it cannot operate on light data
5. ArtifactAgent is being called — artifact quality requires full research
6. User says "tell me more" or equivalent

**Pre-deep clarification — one optional question before full research:**
When full depth is triggered and UserContext is missing information that would materially change what gets researched, the Orchestrator may ask one question before dispatching:
- Activity interests absent → "Any particular focus — food, history, nightlife, nature?" (shapes DestinationResearchAgent and ItineraryPlannerAgent queries)
- Dates completely absent → "Any rough dates in mind?" (determines forecast vs. climate mode for WeatherAgent)

This is not a gate — if the user skips it, the system proceeds with defaults. Only ask if the answer would genuinely change research direction, not just slightly refine it.

**Examples that warrant clarification:**
- "Where can I surf?" — origin unknown; one short question before dispatching: "Roughly where are you based? I'll focus on what's reachable for you." Makes ExplorerAgent results dramatically more relevant.
- "I want to travel somewhere nice" — too open to act usefully; ask: "What kind of trip — beach, city, nature? And roughly what's your budget and where are you flying from?"
- "Plan a 7-day Japan itinerary" — actionable as-is, but budget and travel style materially change the itinerary output; worth a single question before generating: "Any budget range or travel style in mind — backpacker, mid-range, or luxury?"

**Examples that do NOT need clarification — proceed immediately:**
- "Mumbai to Japan in late June for 10 days, what all should I cover?" — origin, destination, dates, and duration all present; "what to cover" is open-ended but that's the output, not a missing input. Call TransportationAgent + DestinationResearchAgent + WeatherAgent in parallel.
- "Compare Bali and Thailand for a budget trip from Bangalore" — three destinations, origin, and budget tier all known. Call research for both in parallel.
- "Is Morocco safe to visit right now?" — direct factual query; dispatch DestinationResearchAgent immediately.
- "What's the cheapest time of year to fly to Japan from Delhi?" — origin and destination clear; dispatch ExplorerAgent + WeatherAgent for seasonal pricing.
- "I have 5 days in Tokyo starting June 20" — enough to build a full plan. Proceed with all relevant specialists.
- "Visa requirements for Vietnam on an Indian passport" — fully specified; dispatch DestinationResearchAgent.
- "Best street food cities in Southeast Asia" — exploratory but self-contained; dispatch ExplorerAgent immediately.

---

## Agent Specifications

### Agentic Harness

All agents — the Orchestrator and every specialist — run on the same `SimpleReActAgent` primitive.

**State:** `SimpleReActAgent` holds a `ConversationHistory` internally, initialised with the agent's system prompt at construction. `run(task: str) -> str` appends the task as a user message and continues from the existing history on every call. Agents are instantiated once per session — their history accumulates across all calls to them.

For specialists, this means: if the Orchestrator calls the same specialist twice (e.g., more questions about a destination already researched), the specialist LLM sees its prior tool calls and results in history and can avoid redundant API requests. The Orchestrator never sees or manages specialist history — it is entirely internal.

**Iteration budget awareness:** Every agent is told its iteration budget upfront. The harness injects a remaining-iterations note into the context before each LLM call:

```
[Iterations remaining: N. Plan your tool use accordingly.]
```

When one iteration remains, the note changes to:

```
[Last iteration. Provide your final answer now — do not call more tools unless strictly necessary.]
```

The agent decides how deep or broad to go based on this budget — calling parallel tools when it needs breadth, serial tools when each call depends on the previous result, and wrapping up earlier if it already has enough. The harness never cuts off the agent with an error; when iterations are exhausted it makes one final LLM call (without tools registered) so the agent can produce a complete response from whatever it has gathered.

**Suggested iteration budgets by agent:**

| Agent | Suggested `max_iterations` | Rationale |
|---|---|---|
| WeatherAgent | 1 | Single API call per request |
| BudgetAgent | 2 | Currency fetch + arithmetic rounds |
| ArtifactAgent | 1 | Single file write |
| ExplorerAgent | 3 | 1–3 web search rounds |
| DestinationResearchAgent (light) | 1 | One broad search |
| DestinationResearchAgent (full) | 4 | 3–4 targeted searches |
| TransportationAgent | 5 | IATA lookups + flight searches + overland fallback |
| ItineraryPlannerAgent | 6 | Multiple venue/hours lookups |
| Orchestrator | 8 | Up to ~3 rounds of parallel specialist calls |

These are defaults; callers can override for specific queries.

---

### Orchestrator

**Pattern:** ReAct — specialists are registered as wrapper tools; the LLM calls them and loops until ready to reply  
**LLM calls per turn:** 1 per ReAct iteration; parallel specialist calls happen within a single iteration via multiple tool_calls  
**Context contains:** UserContext (free-text), KnowledgeState summaries, specialist summary results (as tool messages); full session history in the agent's internal ConversationHistory  
**Context does NOT contain:** Raw API responses, typed Pydantic models, specialist internal tool call transcripts  

**KnowledgeState update pattern:** The Orchestrator registers each specialist as a wrapper tool. When the LLM calls a specialist tool, the wrapper: (1) invokes the specialist object's `run()`, (2) calls the appropriate `KnowledgeState.update_*()` method in Python, (3) returns a plain-text summary as the tool result. The LLM receives only summaries; KnowledgeState is always up-to-date by the time the LLM sees the result.

**System prompt responsibilities:**
- Understand travel planning domain broadly
- Recognise query types and select appropriate specialists
- Apply clarification heuristics
- Call multiple specialists in parallel when beneficial (return multiple tool_calls in one response)
- Synthesise specialist results into a coherent, natural reply

---

### ExplorerAgent

**Pattern:** `SimpleReActAgent(max_iterations=3)` — 1–3 web search rounds  
**State:** Internal ConversationHistory persists across session calls  
**Input:** Exploratory query string derived from UserContext + user message  
**Output:** `list[DestinationCandidate]` — 2–5 options with name, country, vibe tags, budget fit, 1-line rationale, source URL  
**Tools:** `web_search`

Called when: the answer space is unknown (destination not named, or the right destination is itself the question).

Does NOT: run detailed research on any candidate. Returns only enough for the Orchestrator to present a shortlist and prompt the user to narrow down.

---

### DestinationResearchAgent

**Pattern:** `SimpleReActAgent(max_iterations=1 for light, 4 for full)` — depth controls iteration budget  
**State:** Internal ConversationHistory persists across session calls; prior destination searches visible on repeat calls  
**Input:** Destination name, UserContext (nationality for visa, interests for activity focus, travel dates for seasonal context)  
**Output:** `DestinationResearch` — attractions, daily cost estimates, visa requirements, safety summary, festival/holiday calendar for travel window  
**Tools:** `web_search`

Two operating modes controlled by `depth` input parameter:

| Aspect | `"light"` | `"full"` |
|---|---|---|
| Web searches | 1 | 3–4 |
| Vibe / character | ✓ brief | ✓ detailed |
| Budget tier fit | ✓ rough (backpacker / mid / luxury) | ✓ with daily spend estimates |
| Climate for travel window | ✓ sketch (hot/wet/cool) | ✓ deferred to WeatherAgent |
| Top attractions | ✓ 2–3 names only | ✓ with context, tips, time needed |
| Daily cost breakdown | ✗ | ✓ food / transport / accommodation |
| Visa requirements | ✓ complexity tier only (easy / on-arrival / advance required) | ✓ full (documents, fees, links) |
| Safety assessment | ✗ | ✓ |
| Festival / public holiday calendar | ✗ | ✓ for travel window |
| Neighbourhood guide | ✗ | ✓ |
| Interest-tailored activity recommendations | ✗ | ✓ uses UserContext interests |

`"light"` is sufficient for comparison and shortlisting — answering "is this worth considering?" `"full"` is required before building an itinerary, generating an artifact, or answering any specific question about a place.

---

### TransportationAgent

**Pattern:** `SimpleReActAgent(max_iterations=5)` — IATA lookups, flight searches, overland fallback  
**State:** Internal ConversationHistory persists across session calls; cached IATA codes and prior route searches visible on repeat calls  
**Input:** Trip legs as `list[TripLeg]` (each leg: origin, destination, date), UserContext (constraints like "no red-eye", "max 5h flight")  
**Output:** Per leg: `list[FlightDetails]` or overland options. Also: airport transfer options for each endpoint.  
**Tools:** `flight_search` (Amadeus), `web_search`

**IATA resolution:** Resolves city names to IATA codes internally using `flight_search`'s location lookup before querying flight offers. The Orchestrator never needs to know IATA codes.

**Multi-leg handling:** For A→B→C itineraries, searches each leg independently and returns results grouped by leg. Does not attempt to find a single multi-city fare unless both origin and destination are IATA airports (Amadeus multi-city endpoint can be used in that case).

**Overland fallback:** If no flights are found for a leg, or if UserContext constraints exclude flights, uses `web_search` to find train/ferry/bus options and estimated journey time and cost.

---

### WeatherAgent

**Pattern:** `SimpleReActAgent(max_iterations=1)` — single API call per request  
**State:** Internal ConversationHistory persists across session calls  
**Input:** City name, date range or month  
**Output (forecast mode):** `WeatherForecast` — per-day temp (°C/°F), precipitation probability, WMO weather description  
**Output (climate mode):** `ClimateSummary` — monthly averages (temp range, typical rainy days, season characterisation)  
**Tools:** `weather_forecast` (Open-Meteo forecast endpoint), `climate_summary` (Open-Meteo climate endpoint)

**Mode selection** (determined by input date range):
- Dates within 16 days → forecast mode
- Dates beyond 16 days, or only a month specified → climate mode
- Climate mode output is labeled "Historical climate average" in all downstream use

---

### BudgetAgent

**Pattern:** `SimpleReActAgent(max_iterations=2)` — currency fetch, then one or more arithmetic rounds  
**State:** Internal ConversationHistory persists across session calls; exchange rate fetched once and visible in history for reuse  
**Input:** `BudgetInputs` — flight costs (from TransportationAgent), accommodation tier, destination daily cost estimates (from DestinationResearchAgent), duration, UserContext (home_currency, budget_total, group_size)  
**Output:** `BudgetBreakdown` — itemised cost ranges in USD and home currency, total range, delta vs. user budget if stated  
**Tools:** `currency_convert` (Frankfurter API), `calculate` (safe expression evaluator)

Exchange rate is fetched once per session and reused. All arithmetic — splits by group size, per-person vs shared costs, range computations — goes through `calculate` rather than LLM reasoning. `calculate` evaluates a plain arithmetic expression string using an AST-based parser that allows only numeric literals and arithmetic operators; no `eval()`, no function calls, no attribute access. All costs output as ranges (low/high) rather than point estimates. For multi-destination comparisons, returns a `list[BudgetBreakdown]` in the same order as destinations were input.

---

### ItineraryPlannerAgent

**Pattern:** `SimpleReActAgent(max_iterations=6)` — multiple web search rounds for venues, hours, travel times  
**State:** Internal ConversationHistory persists across session calls  
**Input:** Destination(s), confirmed dates, `DestinationResearch` per city, `WeatherForecast` per city, UserContext (interests, travel style, pace preference), trip structure (multi-city leg order and dates if applicable)  
**Output:** `Itinerary` — structured day-by-day plan with morning/afternoon/evening slots, estimated time per activity, travel notes between activities  
**Tools:** `web_search`

**Scheduling rules:**
- Day 1: arrival day — light schedule, orientation activities only
- Final day: departure day — morning slot only
- Weather-aware: days with >60% precipitation probability get indoor-heavy alternatives
- Multi-city: transit days (inter-city travel) are scheduled explicitly with realistic journey time
- Public holidays and festival days at the destination are incorporated (closures, special events)

---

### ArtifactAgent

**Pattern:** `SimpleReActAgent(max_iterations=1)` — single file write  
**State:** Internal ConversationHistory persists across session calls; prior artifact filenames visible, enabling correct version increment  
**Input:** Artifact request (what the user wants in the document) + full session context (UserContext, KnowledgeState, Itinerary if generated)  
**Output:** Markdown file written to disk  
**Tools:** `file_write`

**Filename convention:** `{type}_{destination}_{YYYY-MM[-DD]}_v{N}.md`  
Examples: `itinerary_tokyo_2026-06-20_v1.md`, `comparison_bali_vs_portugal_2026-09_v1.md`

Version `N` increments on each refinement request within the same session. Files are never overwritten.

**Footer** appended to every artifact:
```
---
Generated: {timestamp}
Data sources: {list of agents called and APIs used}
Pricing is estimated — verify before booking.
```

---

## Tool Registry

All tools follow the same contract: return a dict, never raise. On failure: `{"status": "error", "error": "...", "fallback": "..."}`.

| Tool | Owner agents | External call |
|---|---|---|
| `web_search(query, num_results=5)` | Explorer, DestinationResearch, Transportation, ItineraryPlanner | Tavily API |
| `flight_search(origin, destination, date, max=3)` | Transportation | Amadeus API |
| `weather_forecast(city, start_date, end_date)` | Weather | Open-Meteo forecast |
| `climate_summary(city, month)` | Weather | Open-Meteo climate |
| `currency_convert(amount, from_currency, to_currency)` | Budget | Frankfurter API |
| `calculate(expression, label)` | Budget | local (AST-based safe evaluator, no external call) |
| `file_write(filename, content)` | Artifact | local filesystem |

---

## Conversation History Format

All agents use the OpenAI messages format, making the system compatible with any provider:

```python
[
  {"role": "system",    "content": "<agent system prompt>"},
  {"role": "user",      "content": "<user message or orchestrator task>"},
  {"role": "assistant", "content": null,
                        "tool_calls": [{"id": "...", "type": "function",
                                        "function": {"name": "...", "arguments": "..."}}]},
  {"role": "tool",      "tool_call_id": "...", "content": "<tool result JSON>"},
  {"role": "assistant", "content": "<final response>"}
]
```

The Orchestrator maintains the full ConversationHistory (user ↔ Orchestrator exchanges). Each specialist receives only what it needs for its specific task — not the full conversation.

---

## Data Flow: Selected Query Traces

### "I want to travel somewhere nice"

```
Turn 1
  Orchestrator: ambiguity check → too vague to act
  Response: "What kind of trip are you thinking — beach, city, or nature?
             And roughly what's your budget and how long do you have?"

Turn 2 (user: "city vibes, 5 days, mid-range, from Delhi")
  Orchestrator: updates UserContext

  ReAct iteration 1 — tool_calls:
    ExplorerAgent("best city trips 5 days mid-range from Delhi June")
  → returns: Prague, Bangkok, Tbilisi, Kuala Lumpur

  ReAct iteration 2 — tool_calls (parallel):
    DestinationResearchAgent(Prague, depth="light")
    DestinationResearchAgent(Bangkok, depth="light")
    DestinationResearchAgent(Tbilisi, depth="light")
    DestinationResearchAgent(KL, depth="light")
    WeatherAgent(Prague, June, climate mode)
    WeatherAgent(Bangkok, June, climate mode)
    WeatherAgent(Tbilisi, June, climate mode)
    WeatherAgent(KL, June, climate mode)

  ReAct iteration 3 — tool_calls:
    BudgetAgent (rough comparison from light research data)

  Final response: shortlist with 4 options
```

### "Mumbai to Tokyo, June 20–30, ₹2.5L"

```
Turn 1
  Orchestrator: preferences clear, no clarification needed

  ReAct iteration 1 — tool_calls (parallel):
    TransportationAgent(BOM→NRT, June 20)
    WeatherAgent(Tokyo, June 20–30)
    DestinationResearchAgent(Tokyo, depth="full")

  ReAct iteration 2 — tool_calls:
    BudgetAgent(flight + destination costs, budget=₹2.5L)

  ReAct iteration 3 — tool_calls:
    ItineraryPlannerAgent(10 days, weather-aware)

  Final response (ArtifactAgent called only if user requests)
```

### "When should I visit Japan?"

```
Turn 1
  Orchestrator: destination known, dates unknown → timing query

  ReAct iteration 1 — tool_calls (parallel):
    WeatherAgent(Japan, all months, climate mode)
    DestinationResearchAgent(Japan, seasonal context + events)
    ExplorerAgent("Japan travel peak season pricing by month")

  ReAct iteration 2 — tool_calls:
    BudgetAgent(flight cost ranges by season)

  Final response: off-peak windows, cherry blossom window,
  Golden Week avoidance, autumn foliage option — with pricing context
```

---

## LLM Client

All agents use the same `LLMClient` which posts to `{LLM_BASE_URL}/chat/completions` via raw `httpx`. The client:
- Reads `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` from config
- Passes any headers defined in `LLM_EXTRA_HEADERS` (JSON string in config) — use this for provider-specific headers such as `anthropic-version`
- Returns the raw `choices[0].message` dict — agents inspect `finish_reason` and `tool_calls` directly
- Does not retry, buffer, or transform responses

Swapping providers requires only a `.env` change. No provider-specific logic lives in the client.

---

## Extensibility

| Future capability | Integration point |
|---|---|
| Google Places (POI search, ratings) | DestinationResearchAgent, ItineraryPlannerAgent — add `places_search` tool |
| Google Routes (door-to-door time) | TransportationAgent, ItineraryPlannerAgent — add `route_time` tool |
| Real-time events (concerts, festivals) | DestinationResearchAgent — add `events_search` tool |
| Hotel search API | New AccommodationAgent; BudgetAgent consumes its output |
| Cross-session memory | Orchestrator — add `memory_read` / `memory_write` tools; UserContext and KnowledgeState can be persisted and restored |
| Streaming responses | LLMClient — add streaming mode; Orchestrator synthesis call streams to CLI |

Adding a new specialist requires registering it as a tool on the Orchestrator — the ReAct loop picks it up automatically with no other changes.
