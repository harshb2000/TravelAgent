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
            Research                                ▼
                                          Itinerary
                                          Planner
                                               ▼
                                          Artifact
```

Each specialist runs with its own system prompt and tool set. Raw API data never enters the Orchestrator's context — only structured summaries come back.

---

## Data Models

### UserContext

The Orchestrator maintains a `UserContext` dataclass that accumulates and updates as the conversation progresses. The context string is passed to specialists; `wordset` and `blocklist` power fast candidate pre-firing checks without re-running the NLTK pipeline on every render.

```
UserContext:
  context: str              # running natural language summary of who is travelling,
                            # from where, what they want, constraints, and anything else relevant.
                            # Appended to or corrected by the Orchestrator each turn. Never reset.
  wordset:  frozenset[str]  # NLTK-processed positive-intent terms — blocklisted terms excluded.
                            # (tokenise → remove stop words → lemmatise → subtract blocklist).
                            # Recomputed when `context` changes. Used for O(1) Jaccard scoring.
  blocklist: frozenset[str] # Explicitly negated entities extracted from `context` by a lightweight
                            # negation parser (patterns: "not X", "avoid X", "no X", "skip X",
                            # "except X", "don't want X", "not interested in X").
                            # Recomputed when `context` changes, same pass as `wordset`.
                            # Used for hard exclusion in wrapper pre-firing checks — any candidate
                            # whose name.lower() is in blocklist scores 0 regardless of Jaccard.
```

Note on why embeddings were not chosen: sentence embeddings do not reliably handle negation — "not Thailand" and "Thailand" produce similar vectors because semantic content is largely shared. Jaccard on a positive-intent wordset with explicit hard exclusion via `blocklist` is simpler, dependency-free, and more predictable.

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
A few values need a specific format for API calls (exact dates for SerpApi, ISO currency code for Frankfurter). These are extracted from the context string by the Orchestrator when a specialist needs them — not maintained as persistent typed fields:

| Hint | Extracted for | Example |
|---|---|---|
| `date_range` | WeatherSpecialist, TransportationSpecialist | "June 20–30 2026" |
| `budget_range` | BudgetSpecialist | "₹40,000–₹50,000 per person" |
| `home_currency` | BudgetSpecialist | "INR" |
| `nationality` | DestinationResearchSpecialist (visa) | "Indian" |

The `date_range` hint is also what the Orchestrator passes as an argument when calling time-sensitive specialist tools (`weather_agent(destination, date_range=...)`, `flight_search(origin, destination, date_range=...)`). The wrapper tool constructs the typed `DateRange` object from this string and uses it as the KnowledgeState key.

If a hint is not present and is needed, the Orchestrator either asks a clarifying question or makes a stated assumption before dispatching — with one exception: for light-depth destination comparisons, dates are not required. The Orchestrator passes `date_range="next few months"` and the specialist uses climate mode. This assumption is stated in the response ("I'm looking at typical conditions for the coming months"). Queries where timing is irrelevant (safety, visa requirements, general research) do not receive a date_range argument at all.

**Origin city is not a required field and never a session gate.** It is part of the free-text context and may be absent, single-valued, or multi-valued ("2 from Delhi, 2 from Mumbai"). TransportationSpecialist receives the full context string and determines what routes to search based on it.

### KnowledgeState

What has been learned about each destination or option during the session.

```
DateRange:
  label:      str           # canonical key: "June 2026", "late June", "2026-06-20 to 2026-06-30"
  start_date: str | None    # ISO date when specific; None for vague ranges ("late June", "autumn")
  end_date:   str | None    # ISO date when specific; None for vague ranges

  # Constructor used by wrapper tools — LLM only ever passes a plain string
  from_string(s: str) -> DateRange
    parses "YYYY-MM-DD to YYYY-MM-DD" → populates start_date + end_date
    parses "YYYY-MM-DD"               → populates start_date only
    otherwise                         → label-only (start_date=None, end_date=None)

RouteKey:                             # frozen dataclass — hashable dict key
  origin:      str                    # city name e.g. "Mumbai"
  destination: str                    # city name e.g. "Tokyo"

DestinationCandidate:
  name:        str
  country:     str
  vibe_tags:   list[str]              # e.g. ["beach", "budget-friendly", "nightlife"]
  rationale:   str                    # 1-line reason this matches the user's query
  source_url:  str
  query:       str                    # the user query that generated this candidate;
                                      # allows the orchestrator to reason about relevance
                                      # if the user's intent shifts mid-session
  added_at:    int                    # turn index when this candidate was added
  wordset:     frozenset[str]         # NLTK-preprocessed word set of (rationale + query +
                                      # vibe_tags + name). Computed once at creation;
                                      # never updated — candidates are immutable after addition.

Activity:
  name:         str
  tags:         list[str]             # e.g. ["outdoor", "adventure", "cultural", "nightlife"]
  indoor:       bool                  # used by ItineraryPlannerSpecialist for weather-aware scheduling
  duration_min: int | None            # deferred — populated by ItineraryPlannerSpecialist
  source_url:   str | None            # URL from web_search result that provided this activity

StringWithAttribution:
  text:         str
  source_url:   str | None            # URL from web_search result that provided this claim

CostWithAttribution:
  amount:       float                 # USD
  source_url:   str | None            # URL from web_search result that provided this cost estimate

DestinationResearch:
  name:             str
  country:          str
  depth:            "light" | "full"
  vibe:             str               # 1–2 sentences in light; richer in full
  top_attractions:  list[str]         # names only throughout; selected by popularity and user
                                      # preferences when known. Activities fills in detail later
                                      # and gives these higher scheduling priority.
  summary:          str               # LLM-generated narrative, populated in the same structured
                                      # output call as the structured fields. Covers seasonal
                                      # nuances, safety caveats, festival timing, highlights —
                                      # whatever templates cannot express. Always set in both modes.
  # full mode only (None in light):
  visa_complexity:  dict[str, StringWithAttribution] | None
                                      # keys are passport+visa profiles, e.g. "Indian passport",
                                      # "Indian passport + valid US visa". Values are free-form
                                      # strings with source, e.g. text="e-visa $25, 3–5 days",
                                      # source_url="https://...". Not populated until relevant
                                      # profiles known from UserContext.
  safety_summary:   StringWithAttribution | None
  festivals:        list[str] | None  # highlights to target and busy periods affecting prices/crowds
  neighbourhoods:   dict[str, StringWithAttribution] | None   # name → description + source
  activities:       list[Activity] | None   # interest-tailored; cost/duration deferred

DestinationBudget:                    # all values USD; keys are LLM-generated, refined by UserContext
  accommodation:     dict[str, CostWithAttribution]  # per unit/night
  food:              dict[str, CostWithAttribution]  # per person
  local_transport:   dict[str, CostWithAttribution]  # per person (transit) or per vehicle (cabs)
  activities:        dict[str, CostWithAttribution]  # per person

TravelOption:
  mode:         str                  # "flight/one-way", "flight/return",
                                     # "train", "bus", "ferry", "taxi", "metro"
  operator:     str | None           # airline, train operator, taxi company, etc.
  origin:       str                  # granular location e.g. "BOM Airport, Mumbai",
                                     # "Shinjuku station, Tokyo", or city name for transfers
  destination:  str
  duration_min: int | None
  cost_usd:     float | None         # for "flight/return": same round-trip total as outbound
                                     # BudgetSpecialist skips mode="flight/return" in budget sum
  flight:       FlightOption | None  # populated for mode="flight/*" only; holds airline,
                                     # flight_number, stops, departure, arrival, IATA codes
  source_url:   str | None           # URL from web_search; None for flight/* (SerpApi structured data)
  note:         str | None

TimeSlot:
  start_time:     str                # "09:00" or loose label e.g. "afternoon"
  activity:       Activity           # embedded; enriched by ItineraryPlannerSpecialist
  location:       str | None         # specific venue name
  notes:          str | None         # booking tips, access notes
  is_alternative: bool               # True = this slot is a weather alternative to the
                                     # preceding non-alternative slot in the day's slot list.
                                     # Prompt constrains: ≤2 alternatives per primary slot,
                                     # ≤3 alternative slots per day total.

ItineraryDay:
  day_num:      int                  # 1-indexed; day 1 = arrival day
  location:     str                  # city/destination
  is_arrival:   bool
  is_departure: bool
  is_transit:   bool                 # inter-city travel day; slots describe transit leg
  slots:        list[TimeSlot]
  weather_note: str | None           # e.g. "Rain expected — indoor alternatives shown"

Itinerary:
  destinations: list[str]            # ordered for multi-city trips
  start_date:   str | None           # ISO date; None if dates not yet confirmed
  days:         list[ItineraryDay]
  notes:        str | None           # trip-level notes (visa reminders, packing, etc.)

DestinationKnowledge:
  research:  DestinationResearch | None   # depth lives here
  weather:   dict[DateRange, WeatherOutput]
  budget:    DestinationBudget | None

RouteKnowledge:
  options:   dict[DateRange, list[TravelOption]]
             # DateRange("any") for date-invariant options (transfers, fixed-schedule trains)
             # specific DateRange for flight options

KnowledgeState:
  candidates:    list[DestinationCandidate]       # accumulates across session; query field tracks provenance
  destinations:  dict[str, DestinationKnowledge]
  routes:        dict[RouteKey, RouteKnowledge]
  itineraries:   dict[frozenset[str], Itinerary]  # keyed by destination set; same set overwrites
```

All collections start empty and accumulate across turns. `candidates` grows with each ExplorerSpecialist call — old candidates are never dropped, as the user may circle back to earlier suggestions; `query` on each candidate lets the orchestrator reason about which candidates match the current intent. If the user asks "what about November instead?", a new `DateRange("November 2026")` entry is added rather than overwriting June data. A new `RouteKey("Delhi", "Tokyo")` entry is added independently of `RouteKey("Mumbai", "Tokyo")` — supporting cases like two travellers joining from different origins.

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
add_candidates(results: list[DestinationCandidate]) → None      # appends; never replaces
update_research(destination: str, result: DestinationResearch) → None
update_weather(destination: str, date_range: DateRange, result: WeatherOutput) → None
update_route(origin: str, destination: str, date_range: DateRange, options: list[TravelOption]) → None
             # date_range = DateRange("any") for transfers and fixed-schedule ground transport
update_destination_budget(destination: str, result: DestinationBudget) → None
update_activities(destination: str, activities: list[Activity]) → None
             # targeted update to DestinationResearch.activities; no other fields touched
update_itinerary(destinations: frozenset[str], itinerary: Itinerary) → None
to_prompt_context() → str    # compact skeleton injected into every Orchestrator turn
```

Raw specialist output (typed Pydantic models) never enters the LLM's context — only the summary string returned by the wrapper does.

**`to_prompt_context()` — the KnowledgeState skeleton**

Injected into every Orchestrator turn so the LLM can reason about what is already known and what is still missing without seeing raw data. Format:

```
CANDIDATES (N): <name> [<vibe_tags> · "<query>"], ...

DESTINATIONS
  <Name>  [<depth>]
    weather (<DateRange>):      ✓ (forecast|climate) | —
    destination budget:         ~$<low>–<high>/day   | —
    visa (<home_country>):      <tier>               | — (home country not set)

ROUTES  (BFS-composed city→city paths)
  <Origin> → <Destination>  (<DateRange>)
    ✓ from $<min_cost> (<operator>, <stops> stop(s), <duration>h) · <N> options
      departure transfer: <mode> $<cost>[, <mode> $<cost>]
      arrival transfer:   <mode> $<cost>[, <mode> $<cost>]
    or  ✓ <mode> · <operator> · ~<duration>h · ~$<cost>  (overland-only)
    or  —
```

`to_prompt_context()` runs a BFS over stored `RouteKey` edges to compose city-level paths. An edge is valid for a given `DateRange` if `RouteKnowledge.options` contains that `DateRange` **or** `DateRange("any")`. The routes section shows only the Orchestrator-level `RouteKey` (city→city); granular intermediate nodes (airport, station) are not surfaced.

**Destination budget range computation:** low = sum of `min(category.values())` across all `DestinationBudget` categories; high = sum of `max(category.values())`.

The orchestrator system prompt carries two standing caveats:
- *"Budget figures in the context summary are rough approximations. Dispatch BudgetSpecialist for accurate totals for specific trip configurations."*
- *"Round-trip prices cover both directions — count once in budget, not per leg."*

**Candidate scoring and top-N selection**

`to_prompt_context(user_context: str) -> str` scores all accumulated candidates and shows only the top `TOP_N_CANDIDATES = 5` (constant). The skeleton line reads `CANDIDATES (showing 3 of 7):` when the full list is longer, so the orchestrator knows more exist.

Scoring uses two components, each **normalised to [0, 1] within the current candidate set** before combining — without per-set normalisation the components operate on incompatible scales and the weighted sum is meaningless:

```
recency_i = 1 / (current_turn − added_at_i + 1)
jaccard_i = |candidate_i.wordset ∩ user_context.wordset| /
            |candidate_i.wordset ∪ user_context.wordset|

normalized_recency_i = recency_i / max(recency_j)
normalized_jaccard_i = jaccard_i / max(jaccard_j)   # if max == 0, all set to 0

score_i = ALPHA × normalized_recency_i + (1 − ALPHA) × normalized_jaccard_i
```

Constants: `ALPHA = 0.3` (lean toward relevance over recency), `TOP_N_CANDIDATES = 5`.

Both `candidate.wordset` and `user_context.wordset` are pre-built — `to_prompt_context()` performs only set intersection/union at render time (O(1) per candidate). Because `user_context.wordset` already excludes blocklisted terms, negated destinations are naturally deprioritised in the Jaccard score; hard exclusion via `user_context.blocklist` (see UserContext above) catches any remaining edge cases before scoring runs. The NLTK pipeline (tokenise → remove stop words → lemmatise via `WordNetLemmatizer`) runs only when source text changes: once at candidate creation, and on each `UserContext` update. Requires NLTK data: `stopwords`, `wordnet`, `punkt_tab`.

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
       with it (e.g. "where can I surf?" benefits from knowing the region; ExplorerSpecialist
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
4. ItineraryPlannerSpecialist is being called — it cannot operate on light data
5. ArtifactSpecialist is being called — artifact quality requires full research
6. User says "tell me more" or equivalent

**Pre-deep clarification — one optional question before full research:**
When full depth is triggered and UserContext is missing information that would materially change what gets researched, the Orchestrator may ask one question before dispatching:
- Activity interests absent → "Any particular focus — food, history, nightlife, nature?" (shapes DestinationResearchSpecialist and ItineraryPlannerSpecialist queries)
- Dates completely absent → "Any rough dates in mind?" (determines forecast vs. climate mode for WeatherSpecialist)

This is not a gate — if the user skips it, the system proceeds with defaults. Only ask if the answer would genuinely change research direction, not just slightly refine it.

**Examples that warrant clarification:**
- "Where can I surf?" — origin unknown; one short question before dispatching: "Roughly where are you based? I'll focus on what's reachable for you." Makes ExplorerSpecialist results dramatically more relevant.
- "I want to travel somewhere nice" — too open to act usefully; ask: "What kind of trip — beach, city, nature? And roughly what's your budget and where are you flying from?"
- "Plan a 7-day Japan itinerary" — actionable as-is, but budget and travel style materially change the itinerary output; worth a single question before generating: "Any budget range or travel style in mind — backpacker, mid-range, or luxury?"

**Examples that do NOT need clarification — proceed immediately:**
- "Mumbai to Japan in late June for 10 days, what all should I cover?" — origin, destination, dates, and duration all present; "what to cover" is open-ended but that's the output, not a missing input. Call TransportationSpecialist + DestinationResearchSpecialist + WeatherSpecialist in parallel.
- "Compare Bali and Thailand for a budget trip from Bangalore" — three destinations, origin, and budget tier all known. Call research for both in parallel.
- "Is Morocco safe to visit right now?" — direct factual query; dispatch DestinationResearchSpecialist immediately.
- "What's the cheapest time of year to fly to Japan from Delhi?" — origin and destination clear; dispatch ExplorerSpecialist + WeatherSpecialist for seasonal pricing.
- "I have 5 days in Tokyo starting June 20" — enough to build a full plan. Proceed with all relevant specialists.
- "Visa requirements for Vietnam on an Indian passport" — fully specified; dispatch DestinationResearchSpecialist.
- "Best street food cities in Southeast Asia" — exploratory but self-contained; dispatch ExplorerSpecialist immediately.

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
| WeatherSpecialist | 1 | Single API call per request |
| BudgetSpecialist | 5 | Parallel web searches + currency + arithmetic + response |
| ArtifactSpecialist | 3 | Fetch summaries → draft → self_critique → refine + write |
| ExplorerSpecialist | 3 | 1–3 web search rounds |
| DestinationResearchSpecialist (light) | 1 | One broad search |
| DestinationResearchSpecialist (full) | 4 | 3–4 targeted searches |
| TransportationSpecialist | wrapper-set | `min(2 + len(missing_routes), 5)` |
| ItineraryPlannerSpecialist | 6 | Multiple venue/hours lookups |
| Orchestrator | 8 | Up to ~3 rounds of parallel specialist calls |

These are defaults; callers can override for specific queries.

---

### Orchestrator

**Pattern:** ReAct — specialists are registered as wrapper tools; the LLM calls them and loops until ready to reply  
**LLM calls per turn:** 1 per ReAct iteration; parallel specialist calls happen within a single iteration via multiple tool_calls  
**Context contains:** UserContext (free-text), KnowledgeState skeleton, specialist summary results (as tool messages); full session history in the agent's internal ConversationHistory  
**Context does NOT contain:** Raw API responses, typed Pydantic models, specialist internal tool call transcripts  

**Tools:** all specialist wrapper tools + `update_user_context`

**`update_user_context(new_context: str)`**  
The LLM calls this to update the running UserContext when the user provides new information. The tool sets `UserContext.context = new_context` and triggers NLTK recomputation of `wordset` and `blocklist` (tokenise → remove stop words → lemmatise; negation parser for blocklist). The LLM sees the current context in the task string and writes an updated version incorporating the new message — replacement, not append, giving full control over corrections ("no, Mumbai not Delhi").

**Ordering rule:** If a turn requires both a context update and specialist calls, the LLM must call `update_user_context` first (alone, in iteration 1) so specialists see the fresh context. The system prompt enforces this: *"If the user's message changes the trip context, call `update_user_context` first before dispatching any specialist."*

**Turn structure:**
```
turn(user_input: str) -> str:
  task = f"UserContext:\n{user_context.context}\n\n"
       + f"KnowledgeState:\n{knowledge.to_prompt_context()}\n\n"
       + f"User: {user_input}"
  return self._agent.run(task)
```
The task string is rebuilt each turn with the current UserContext and skeleton. The agent's internal ConversationHistory carries the full session; `run(task)` appends this turn's task and continues.

**KnowledgeState update pattern:** The Orchestrator registers each specialist as a wrapper tool. When the LLM calls a specialist tool, the wrapper:
1. **Pre-firing check** — inspects KnowledgeState. Full cache hit → return summary without invoking. Partial hit → adjust inputs. No pre-firing check for BudgetSpecialist and ItineraryPlannerSpecialist (always fire).
2. **Invoke** — calls `specialist.run()` with the (possibly adjusted) inputs.
3. **Update** — calls the appropriate `KnowledgeState.update_*()` method with the typed result.
4. **Summarise** — returns a plain-text summary to the Orchestrator LLM. Template-based for most specialists; `research.summary` verbatim for DestinationResearchSpecialist; `result.breakdown` verbatim for BudgetSpecialist; file path for ArtifactSpecialist.
5. **Exception handling** — if `specialist.run()` raises, the wrapper catches it and returns an error string as the tool result (e.g. `"TransportationSpecialist failed: SerpApi quota exceeded"`). The Orchestrator LLM sees the error and handles it gracefully in its response. Nothing is written to KnowledgeState.

The Orchestrator receives only summaries; KnowledgeState is always up-to-date by the time the LLM sees the result.

**KnowledgeState-aware tool construction:** Three tool groups require a `KnowledgeState` reference at construction time — passed by the Orchestrator (or WeatherSpecialist wrapper) at build time; always see the latest state since Python passes by reference:
- `SliceWeatherRangeTool(knowledge_state)` — constructed by the WeatherSpecialist wrapper; reads existing `WeatherOutput` entries and calls `update_weather()`
- `Get*CompiledTool(knowledge_state)`, `GetItineraryTool(knowledge_state)` — constructed by the ArtifactSpecialist wrapper; reads structured KnowledgeState data for document compilation

**System prompt responsibilities:**
- Understand travel planning domain broadly
- Call `update_user_context` first when the user provides new trip information
- Recognise query types and select appropriate specialists
- Apply clarification heuristics (see Orchestrator Decision Logic)
- Call multiple specialists in parallel when beneficial (return multiple tool_calls in one response)
- Synthesise specialist results into a coherent, natural reply

---

### ExplorerSpecialist

**Pattern:** `SimpleReActAgent(max_iterations=3)` — 1–3 web search rounds  
**State:** Internal ConversationHistory persists across session calls  
**Input from orchestrator wrapper:**
- `query: str` — exploration query derived from UserContext + user message; negative constraints from UserContext (e.g. "not Thailand, not beaches") are embedded in the query string explicitly
- `max_results: int` — default 5; reduced by the wrapper on a partial cache hit (see below)

**Output:** `list[DestinationCandidate]` — each with name, country, vibe_tags, rationale, source_url, query, added_at, wordset  
**Tools:** `web_search`

**Pre-firing check (wrapper) — two stages:**

**Stage 1 — Hard exclusion:** Remove any existing candidate whose `name.lower()` appears in `user_context.blocklist`. These are never returned regardless of similarity score. If a blocklisted destination was previously cached, it is silently dropped from cache hit counts.

**Stage 2 — Jaccard similarity:** On the surviving (non-excluded) candidates, compute Jaccard similarity between the incoming `query`'s positive wordset (stop words and blocklist terms removed) and each existing `candidate.wordset`. Count how many score above `EXPLORER_CACHE_THRESHOLD = 0.6`.

| Surviving candidates above threshold (K) | Action |
|---|---|
| ≥ `max_results` | Full cache hit — return template summary of top K candidates; do not fire specialist |
| 0 < K < `max_results` | Partial cache hit — fire specialist with `max_results = max_results − K`; pass the K surviving candidates into the specialist prompt so it does not repeat them |
| 0 | Full miss — fire specialist with original `max_results` |

**Specialist prompt on partial/full miss:** includes the surviving non-excluded candidate list exhaustively with instruction not to suggest any already listed destination. Negative constraints from UserContext are also embedded in the query string passed to the specialist — the LLM handles negation in prose.

**Orchestrator summary (template):**
```
Found N candidates [K from cache, M new]:
  Prague (Czech Republic) — city/culture, fits mid-range budget from Delhi [source]
  Bangkok (Thailand) — city/budget, vibrant street scene [source]
  ...
```

Called when: the answer space is unknown (destination not named, or the right destination is itself the question).

Does NOT: run detailed research on any candidate. Returns only enough for the Orchestrator to present a shortlist and prompt the user to narrow down.

---

### DestinationResearchSpecialist

**Pattern:** `SimpleReActAgent` — iteration budget set by wrapper based on pre-firing check case (see table below)  
**State:** Internal ConversationHistory persists across session calls; prior destination searches visible on repeat calls  
**Input from orchestrator wrapper:**
- `destination: str` — destination name
- `depth: "light" | "full"` — research depth
- `user_context: str` — full UserContext string (small enough to pass directly; specialist extracts nationality, interests, travel dates as needed)

**Output:** `DestinationResearch`  
**Tools:** `web_search`

**Depth modes:**

| Aspect | `"light"` | `"full"` |
|---|---|---|
| Web searches | 1 | 3–4 |
| Vibe / character | ✓ brief | ✓ detailed |
| Top attractions | ✓ 2–3 names | ✓ open to enrichment as interests clarify |
| Budget tier fit | ✓ rough (backpacker / mid / luxury) | ✓ deferred to BudgetSpecialist |
| Climate for travel window | ✓ sketch (hot/wet/cool) | ✓ deferred to WeatherSpecialist |
| Safety assessment | ✗ | ✓ |
| Festivals / public holidays | ✗ | ✓ for travel window |
| Neighbourhood guide | ✗ | ✓ |
| Visa complexity | ✗ | ✓ keyed by known passport+visa profiles from UserContext |
| Activity detail (cost, duration) | ✗ | ✗ deferred to ItineraryPlannerSpecialist |

`summary: str` is always populated — LLM-generated in the same structured output call as the structured fields. Covers seasonal nuances, safety context, festival timing, and highlights that templates cannot express. The wrapper passes it verbatim to the Orchestrator rather than building a template summary.

`"light"` is sufficient for comparison and shortlisting — answering "is this worth considering?" `"full"` is required before building an itinerary, generating an artifact, or answering any specific question about a place.

**Pre-firing check (wrapper) — four cases:**

| KnowledgeState state | Requested depth | Action | `max_iterations` |
|---|---|---|---|
| No research exists | either | Full miss — fire specialist | 1 (light) or 4 (full) |
| `depth="light"` exists | `"light"` | Cache hit — return `research.summary`; do not fire | — |
| `depth="full"` exists | `"light"` | Cache hit (full is superset) — return `research.summary`; do not fire | — |
| `depth="light"` exists | `"full"` | Upgrade — fire specialist; prior light search visible in history | 3 |
| `depth="full"` exists | `"full"` | Pass-through — fire specialist; specialist self-directs | 4 |

**Why light caches but full passes through:** Light data (`vibe`, `top_attractions`, `summary`) has no UserContext-dependent fields — it is always correct to return as-is. Full data may need enrichment as UserContext evolves: `visa_complexity` can be populated once a passport profile is known, `top_attractions` can be expanded as interests clarify. The specialist sees its prior searches in ConversationHistory and the current UserContext in one call — it decides whether to do additional searches or return early. The wrapper does not need to track what UserContext contained at the time of the last research call.

**`visa_complexity` population:** Deferred until at least one passport+visa profile is known from UserContext. Keys describe the traveller's profile, e.g. `"Indian passport"`, `"Indian passport + valid US visa"`. Values are free-form strings, e.g. `"advance-required"`, `"on-arrival"`, `"visa-free — no action needed"`, `"e-visa available online, $25, 3–5 business days"`. Populated via a visa-update run (max_iterations=1) once the profile is known; can be incrementally extended if additional profiles emerge.

**Orchestrator summary:** `research.summary` verbatim — no template construction in the wrapper for this specialist.

Called when: destination is known and the Orchestrator needs research to present options, answer questions about a place, build a budget, or plan an itinerary.

---

### TransportationSpecialist

**Pattern:** `SimpleReActAgent` — `max_iterations` set by wrapper: `min(2 + len(missing_routes), 5)`  
**State:** Internal ConversationHistory persists across session calls; resolved IATA codes and prior route searches visible on repeat calls  
**Input from orchestrator wrapper:**
- `routes: list[tuple[RouteKey, DateRange]]` — only the city-level pairs with cache misses (full BFS miss or incomplete path)
- `user_context: str` — full UserContext string; specialist extracts constraints (max stops, time preferences, airline preferences)

Existing partial-path edges and cached route summaries are included in the task context.

**Output:** `list[TravelOption]` — flat list; flights constructed from `flight_search` tool results, transfers constructed by LLM from `web_search` results  
**Tools:** `flight_search`, `web_search`

**`flight_search` tool output (revised from Phase 4d):**

Returns top-3 options per leg (guaranteed to cover min-cost, min-duration, and min-stops representatives) plus total count. Keeps LLM context compact while covering the main decision dimensions. Selection: sort by cost → take cheapest; sort by duration → take fastest if not already included; sort by stops → take fewest-stops if not already included; fill any remaining slot with next-cheapest.

```
FlightLegSummary:
  options:     list[FlightOption]   # top 3 covering min-cost, min-duration, min-stops
  total_found: int

FlightSearchOutput:
  trip_type:   "one_way" | "round_trip"
  outbound:    FlightLegSummary
  return_leg:  FlightLegSummary | None  # None for one_way or when departure token unavailable
  status:      "ok" | "partial"         # partial when return_leg unavailable
  note:        str
```

**LLM TravelOption construction:** The tool returns `FlightOption`s with raw IATA codes (`origin_iata="BOM"`, `destination_iata="NRT"`). The LLM converts these to `TravelOption`s, enriching `origin`/`destination` to `"<IATA> Airport, <City>"` format using the city context it resolved in the IATA lookup step — the tool itself has no city context. It also sets `mode` based on `trip_type` and leg position (`"flight/one-way"` for outbound, `"flight/return"` for return leg).

**Route coverage:** The specialist is responsible for ensuring the composed path starts and ends at the Orchestrator's city-level node names. For `RouteKey("Mumbai", "Tokyo")` it stores edges covering:
- Departure transfer: `TravelOption(mode="taxi"|"metro"|..., origin="Mumbai", destination="BOM Airport, Mumbai")`
- Flight: `TravelOption(mode="flight/one-way", origin="BOM Airport, Mumbai", destination="NRT Airport, Tokyo", flight=<FlightOption>)`
- Arrival transfer: `TravelOption(mode="taxi"|"metro"|..., origin="NRT Airport, Tokyo", destination="Tokyo")`

For round-trip, return flight options are stored under `RouteKey("NRT Airport, Tokyo", "BOM Airport, Mumbai")` with `mode="flight/return"`.

**IATA resolution:** Resolves city names to IATA codes via `web_search` before calling `flight_search`. Prior-session resolutions in ConversationHistory — no redundant lookups. Cities with multiple airports searched together (`origin_airports=["BOM", "NMI"]`).

**Pre-firing check (wrapper) — BFS:**

Builds a directed graph from all stored `RouteKey` edges. For each requested `(RouteKey, DateRange)`:
- An edge is BFS-valid if `RouteKnowledge.options` has an entry for the requested `DateRange` **or** `DateRange("any")`
- `DateRange("any")` edges (transfers, fixed-schedule trains) are valid for all dates

| BFS result | Action |
|---|---|
| Complete city→city path found for all requested routes | Cache hit — return composed template; do not fire |
| Any route has no path or only a partial path | Fire specialist; partial-path edges passed in task context |

`max_iterations` set to `min(2 + len(missing_routes), 5)`.

**Wrapper — post-specialist:**
1. Groups flat `list[TravelOption]` by `(option.origin, option.destination)`
2. Calls `update_route(origin, destination, date_range, options)` per group — requested `DateRange` for `mode="flight/*"`, `DateRange("any")` for all other modes
3. Runs BFS over updated graph to compose city→city routes
4. Builds template summary

**Orchestrator summary (template, BFS-composed):**
```
Mumbai → Tokyo (Jul 13):  [new]
  ✓ from $280 ow · Air India · 1-stop · 11h  (8 options found)
    departure transfer: taxi $30, metro $10
    arrival transfer:   metro $15, cab $50

Mumbai ↔ Tokyo (Jul 13 / Jul 23):  [new]
  ✓ from $450 rt · Air India · 1-stop · 11h  (5 options found)
    arrival transfer (Tokyo): metro $15, cab $50
  [round-trip price covers both directions]

Delhi → Tokyo (Jul 13):  [cached]
  ✓ from $310 ow · IndiGo · 1-stop · 9h  (6 options found)
```

**KnowledgeState updates:** `update_route(origin, destination, date_range, options)` — replaces `update_flights()` and `update_route_budget()`.

Called when: one or more city-pair routes need to be searched, or the user asks about travel options between cities.

---

### WeatherSpecialist

**Pattern:** `SimpleReActAgent(max_iterations=2)` — iteration 1: tool calls (parallelised where possible); iteration 2: final answer  
**State:** Internal ConversationHistory persists across session calls  
**Input from orchestrator wrapper:**
- `destination: str` — city name
- `date_range: str` — plain string; wrapper converts to `DateRange` via `DateRange.from_string()`

**Output:** `WeatherOutput` (models/weather.py)  
**Tools:** `weather_forecast`, `climate_summary`, `slice_weather_range`

**Mode selection** (determined by the specialist from `DateRange`):
- ALL days in the range fall within 16 days of today → `weather_forecast` tool (forecast mode)
- ANY day in the range falls beyond 16 days, OR `start_date`/`end_date` is None → `climate_summary` tool (climate mode)
- Mixing forecast and climate data within a single `WeatherOutput` is not permitted — the boundary check applies to the full range, not just the start date
- Mode is not passed by the orchestrator; the specialist decides

**`slice_weather_range` tool:**
Handles date range refinement against existing KnowledgeState entries — avoids redundant API calls when the requested range is related to an already-fetched one:
- **Slice (subset):** requested range falls entirely within an existing entry → extract the relevant days from the existing `WeatherOutput`, store as a new KnowledgeState entry under the target `DateRange` key. No API call. Issued alone in iteration 1.
- **Augment (extension):** requested range extends an existing entry → `slice_weather_range` and the fresh fetch (`weather_forecast`/`climate_summary` for the missing portion) are issued as **parallel tool calls in a single iteration**. The harness dispatches both concurrently. The **wrapper merges the two results in Python** (concatenates `days` arrays, sorts by date, constructs combined `WeatherOutput`) and calls `update_weather()` — no extra tool, no extra LLM call, no extra iteration.

The specialist is given the existing `weather` entries for `destination` as part of its task context so it can reason about which case applies and whether to refine or fetch fresh.

**Pre-firing check (wrapper):**
Exact key lookup: `knowledge.destinations[destination].weather[date_range]` exists?
- Cache hit → return template summary; do not fire specialist
- Cache miss → fire specialist (specialist may still use `slice_weather_range` internally)

The orchestrator already sees all existing `DateRange` keys via `to_prompt_context()` and will only request a new one when genuinely needed — overlap detection at the wrapper level is not required.

**Orchestrator summary (template):**
```
# Forecast mode:
"<City> <DateRange>: avg high <X>°C / low <Y>°C, <Z>% precip. <WMO description summary>"

# Climate mode:
"<City> <Month> (historical avg): avg high <X>°C / low <Y>°C, ~<Z>mm/day precip. <season note>"
```
Stats derived from `WeatherOutput.days`: mean of `temp_max`, mean of `temp_min`, mean of `precipitation_prob` (forecast) or mean of `precipitation_sum` (climate).

**Error:** `"<city> could not be geocoded — check spelling or try a nearby major city."`

---

### BudgetSpecialist

**Pattern:** `SimpleReActAgent(max_iterations=5)`  
**State:** Internal ConversationHistory persists across session calls; exchange rates fetched once per session and reused from history  
**Input from orchestrator wrapper:**
- `query: str` — free-form trip configuration string from Orchestrator, e.g. "2 people, 7 nights Tokyo late June, flying Mumbai round-trip, mid-range hotel, budget ₹2.5L/person". Free-form handles multi-destination comparisons in a single call.
- Wrapper appends KnowledgeState context: existing `DestinationBudget` snapshot per named destination (if present) + relevant `TravelOption` costs for named routes (skipping `mode="flight/return"` entries to avoid double-counting)

**Output:** `BudgetSpecialistOutput`
```
BudgetSpecialistOutput:
  destination_budget: DestinationBudget | None  # populated/updated if web_search was used to
                                                 # find cost data; None if existing was used as-is
  breakdown: str   # ephemeral formatted trip cost breakdown for the Orchestrator; not stored
```

**Tools:** `web_search`, `currency_convert`, `calculate`

**DestinationBudget ownership:** BudgetSpecialist owns `DestinationBudget`. When cost data is missing or incomplete, it issues parallel `web_search` calls (accommodation, food, activities, local transport — all in one iteration). The narrative summary of costs is part of the ephemeral `breakdown` output and regenerated on each call — it is not stored in `DestinationBudget`.

**Arithmetic discipline:** All numeric computations go through `calculate` rather than LLM reasoning. This includes per-person splits, per-vehicle/per-room scaling by party size, range computations (low/high), and currency conversion application. The LLM decides which expressions to evaluate; `calculate` evaluates them safely.

**Iteration pattern:**
- Iteration 1: parallel `web_search` calls if `DestinationBudget` data is missing — skipped if data already in context
- Iteration 2: `currency_convert` for home currency rate
- Iteration 3: `calculate` rounds for each cost component
- Iteration 4: final response with formatted breakdown

**No pre-firing check** — fires every time a budget query arrives. Wrapper always passes existing KnowledgeState data as context; specialist determines what, if anything, needs fetching.

**KnowledgeState updates:** Wrapper calls `update_destination_budget(destination, result.destination_budget)` when `result.destination_budget` is not None.

**Orchestrator summary:** `result.breakdown` verbatim. Format:
```
Tokyo — 7 nights, 2 people (mid-range)
  Flights (rt, per person):   $450      [$900 total]
  Accommodation (per room/nt): $90–120  [$630–840 total, 7 nights]
  Food (per person/day):       $25–45   [$350–630 total]
  Local transport (per person): $8–15/day [$112–210 total]
  Activities:                  $80–150  [$160–300 total, 2 people]
  ─────────────────────────────────────────────────────
  Total (2 people, USD):       $2,152–2,880
  Total (INR, @83.5):          ₹1,79,694–2,40,480
  Budget (stated):             ₹2,50,000/person = ₹5,00,000
  Delta:                       ₹2,59,520–3,20,306 under budget ✓
```

Called when: the user asks about cost, budget feasibility, or a destination cost comparison.

---

### ItineraryPlannerSpecialist

**Pattern:** `SimpleReActAgent(max_iterations=6)`  
**State:** Internal ConversationHistory persists across session calls; prior itineraries and activity research visible for refinements  
**Input from orchestrator wrapper:**
- `query: str` — free-form trip intent and structure from the Orchestrator, e.g. "10 days Tokyo + 3 days Kyoto, June 20 arrival. User prefers cultural and food experiences, mid-pace."
- Wrapper appends: UserContext string + `DestinationResearch` (full depth required) and `WeatherOutput` per destination from KnowledgeState

`DestinationResearch` must be full depth before this specialist is called — the Orchestrator enforces this via depth escalation rules.

**Output:** `ItineraryPlannerOutput`
```
ItineraryPlannerOutput:
  itinerary:         Itinerary
  activity_updates:  dict[str, list[Activity]]  # destination → enriched Activities found
                                                 # during venue research; empty if nothing new
```

**Tools:** `web_search`

**Scheduling rules:**
- Day 1: arrival day — light schedule, orientation activities only
- Final day: departure day — morning slot only
- Weather-aware: days with `precipitation_prob > 60%` (forecast) or high historical `precipitation_sum` (climate) get indoor-heavy primary slots; outdoor alternatives added as `is_alternative=True` slots immediately following their primary
- Multi-city: transit days (`is_transit=True`) are scheduled explicitly — slots describe the journey leg with realistic travel time
- Festival/public holiday days incorporated: closures flagged in `notes`, special events prioritised

**`web_search` usage:** Parallel calls per destination block — venue opening hours, restaurant recommendations. Each parallel batch covers one destination or one day-range to stay within token limits.

**Known limitation — intra-city transit times:** The specialist assumes reasonable constants (e.g. 20–30 min between nearby attractions) rather than looking up actual transit times. If this proves inaccurate enough to affect schedule viability, the right fix is to let ItineraryPlannerSpecialist request specific transit legs from TransportationSpecialist via the Orchestrator — deferred to v2.

**No pre-firing check** — fires whenever itinerary is requested or refined. Specialist's ConversationHistory holds prior itinerary; refinement requests ("add more food spots", "swap day 3 and 4") are handled as follow-up `run()` calls on the same instance.

**KnowledgeState updates:**
- Wrapper calls `update_itinerary(frozenset(destinations), result.itinerary)`
- Wrapper calls `update_activities(destination, activities)` for each entry in `result.activity_updates` where the list is non-empty

**Orchestrator summary (template):**
```
<N>-day itinerary for <destinations> (<start_date>):
  Day 1 (<location>): Arrival — <orientation activity>, <orientation activity>
  Day 2 (<location>): <morning slot> · <afternoon slot> · <evening slot>
  ...
  Day N (<location>): Departure — morning only
  [Saved to itinerary_<destination>_<date>_v1.md on ArtifactSpecialist call]
```

Called when: confirmed dates and full-depth destination research are both present and the user asks for a day-by-day plan or refinement.

---

### ArtifactSpecialist

**Pattern:** `SimpleReActAgent(max_iterations=3)`  
**State:** Internal ConversationHistory persists across session calls; prior artifact filenames visible for version tracking  
**Input from orchestrator wrapper:**
- `query: str` — the user's artifact request verbatim
- Wrapper injects `knowledge.to_prompt_context()` skeleton as task context so the specialist knows what KnowledgeState data is available before deciding what to fetch

**Output:** `ArtifactOutput(file_path: str)` — actual written path (may be `_v2` if `_v1` existed). No KnowledgeState update.  
**Tools:** `get_research_compiled`, `get_budget_compiled`, `get_weather_compiled`, `get_route_compiled`, `get_candidates_compiled`, `get_itinerary`, `self_critique`, `file_write`

All `get_*_compiled` and `get_itinerary` tools are constructed with a `KnowledgeState` reference at wrapper build time — standard dependency injection, same pattern as tool clients.

**Compiled tool contracts:**

Each compiled tool returns the full relevant KnowledgeState section as structured data (JSON or plain text) — all fields included with source URLs co-located next to the data they attribute. Richer than Orchestrator summaries, which are decision-focused and compact. Format is LLM-readable; the specialist decides how to render it in the document.

`get_research_compiled(destination: str) -> str`  
Returns full `DestinationResearch` — vibe, top_attractions, summary, safety (`StringWithAttribution`), visa complexity (`StringWithAttribution` per profile), neighbourhoods (`StringWithAttribution` per name), festivals, activities (name, tags, indoor, duration, source_url).

`get_budget_compiled(destination: str) -> str`  
Returns full `DestinationBudget` — all cost categories as `CostWithAttribution` (amount + source_url per entry).

`get_weather_compiled(destination: str, date_range: str) -> str`  
Returns full `WeatherOutput` — mode, all `DailyWeather` entries (date, temp_max, temp_min, precipitation).

`get_route_compiled(origin: str, destination: str, date_range: str) -> str`  
Returns all `TravelOption`s for the BFS-composed path — mode, operator, origin, destination, duration_min, cost_usd, source_url (where present), flight details (for flight/* modes).

`get_candidates_compiled() -> str`  
Returns all `DestinationCandidate`s — name, country, vibe_tags, rationale, source_url.

`get_itinerary(destinations: list[str]) -> str`  
Returns full `Itinerary` — start_date, all `ItineraryDay`s (day_num, location, is_arrival/departure/transit), all `TimeSlot`s per day (start_time, activity name/tags/indoor/duration/source_url, location, notes, is_alternative), weather_note where set.

**`self_critique(content: str, query: str) -> str`**  
Makes a focused LLM call that reads the draft against the user query and returns structured critique: missing sections, factual inconsistencies, formatting issues, tone. Does **not** include `to_prompt_context()` — judges document quality against what the user asked for, not against what data exists. The specialist uses it to refine before writing.

**Iteration pattern:**
- Iteration 1: parallel `get_*_compiled` / `get_itinerary` calls for all needed sections (determined from skeleton + query)
- Iteration 2: construct draft and call `self_critique(content=<draft>, query=<query>)` — draft is embedded as the tool argument, not returned as message content
- Iteration 3: apply critique, call `file_write(filename=<name>, content=<revised draft>)`

The draft never appears as a standalone message response — it is always embedded in a tool call argument. This keeps the specialist's output clean and ensures critique always runs before writing.

**Filename convention:** `{subject}_{YYYY-MM[-DD]}_v{N}.md` — constructed by specialist from content.  
Examples: `tokyo_itinerary_2026-06-20_v1.md`, `bali_vs_portugal_comparison_2026-09_v1.md`

**Footer** appended to every artifact:
```
---
Generated: {timestamp}
Flights: Google Flights via SerpApi · Weather: Open-Meteo · Research & costs: Tavily web search
Pricing is estimated — verify before booking.
```

Inline `[source](url)` links from attributed model fields — `Activity.source_url`, `CostWithAttribution.source_url`, `StringWithAttribution.source_url` (safety, neighbourhoods, visa), `TravelOption.source_url`, `DestinationCandidate.source_url` — are woven throughout the document body, not aggregated in the footer.

Called when: the user explicitly requests a saved document.

---

## Tool Registry

All tools follow the same contract: return a dict, never raise. On failure: `{"status": "error", "error": "...", "fallback": "..."}`.

| Tool | Owner agents | External call |
|---|---|---|
| `web_search(query, num_results=5)` | Explorer, DestinationResearch, Transportation, ItineraryPlanner | Tavily API |
| `flight_search(origin_airports, destination_airports, date, trip_type, adults, currency)` | Transportation | SerpApi Google Flights |
| `weather_forecast(city, start_date, end_date)` | Weather | Open-Meteo forecast |
| `climate_summary(city, month)` | Weather | Open-Meteo climate |
| `currency_convert(amount, from_currency, to_currency)` | Budget | Frankfurter API |
| `calculate(expression, label)` | Budget | local (AST-based safe evaluator, no external call) |
| `update_user_context(new_context)` | Orchestrator | UserContext + NLTK pipeline (no external call) |
| `get_research_compiled(destination)` | Artifact | KnowledgeState (no external call) |
| `get_budget_compiled(destination)` | Artifact | KnowledgeState (no external call) |
| `get_weather_compiled(destination, date_range)` | Artifact | KnowledgeState (no external call) |
| `get_route_compiled(origin, destination, date_range)` | Artifact | KnowledgeState (no external call) |
| `get_candidates_compiled()` | Artifact | KnowledgeState (no external call) |
| `get_itinerary(destinations)` | Artifact | KnowledgeState (no external call) |
| `self_critique(content, query)` | Artifact | LLM call (same LLMClient instance) |
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
    ExplorerSpecialist("best city trips 5 days mid-range from Delhi June")
  → returns: Prague, Bangkok, Tbilisi, Kuala Lumpur

  ReAct iteration 2 — tool_calls (parallel):
    DestinationResearchSpecialist(Prague, depth="light")
    DestinationResearchSpecialist(Bangkok, depth="light")
    DestinationResearchSpecialist(Tbilisi, depth="light")
    DestinationResearchSpecialist(KL, depth="light")
    WeatherSpecialist(Prague, June, climate mode)
    WeatherSpecialist(Bangkok, June, climate mode)
    WeatherSpecialist(Tbilisi, June, climate mode)
    WeatherSpecialist(KL, June, climate mode)

  ReAct iteration 3 — tool_calls:
    BudgetSpecialist (rough comparison from light research data)

  Final response: shortlist with 4 options
```

### "Mumbai to Tokyo, June 20–30, ₹2.5L"

```
Turn 1
  Orchestrator: preferences clear, no clarification needed

  ReAct iteration 1 — tool_calls (parallel):
    TransportationSpecialist(BOM→NRT, June 20)
    WeatherSpecialist(Tokyo, June 20–30)
    DestinationResearchSpecialist(Tokyo, depth="full")

  ReAct iteration 2 — tool_calls:
    BudgetSpecialist(flight + destination costs, budget=₹2.5L)

  ReAct iteration 3 — tool_calls:
    ItineraryPlannerSpecialist(10 days, weather-aware)

  Final response (ArtifactSpecialist called only if user requests)
```

### "When should I visit Japan?"

```
Turn 1
  Orchestrator: destination known, dates unknown → timing query

  ReAct iteration 1 — tool_calls (parallel):
    WeatherSpecialist(Japan, all months, climate mode)
    DestinationResearchSpecialist(Japan, seasonal context + events)
    ExplorerSpecialist("Japan travel peak season pricing by month")

  ReAct iteration 2 — tool_calls:
    BudgetSpecialist(flight cost ranges by season)

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
| Google Places (POI search, ratings) | DestinationResearchSpecialist, ItineraryPlannerSpecialist — add `places_search` tool |
| Google Routes (door-to-door time) | TransportationSpecialist, ItineraryPlannerSpecialist — add `route_time` tool |
| Real-time events (concerts, festivals) | DestinationResearchSpecialist — add `events_search` tool |
| Hotel search API | New AccommodationSpecialist; BudgetSpecialist consumes its output |
| Cross-session memory | Orchestrator — add `memory_read` / `memory_write` tools; UserContext and KnowledgeState can be persisted and restored |
| Streaming responses | LLMClient — add streaming mode; Orchestrator synthesis call streams to CLI |

Adding a new specialist requires registering it as a tool on the Orchestrator — the ReAct loop picks it up automatically with no other changes.
