# Evaluation Plan — Orchestrator

## What the Orchestrator Decides Here

Given a user message and the current KnowledgeState, the orchestrator must decide:
1. **Which specialists to call** (and which not to)
2. **In what order** (respecting prerequisites)
3. **Which to batch in parallel** (independent calls in the same turn)
4. **Whether to reuse existing state** (not re-calling for data already present)

---

## Section 1 — Query Routing

> **Assumption for all Section 1 tests**: the user message supplies all information needed to
> act — destination(s), approximate date ranges, and trip duration are present.
> No clarification step is needed. This isolates routing logic from clarification behaviour,
> which is evaluated separately in Section 3.

### Failure Modes

| # | Failure | Prompt signal that should prevent it |
|---|---|---|
| F1 | Explorer called when destination already decided | Prompt: Explorer is for undecided destination only |
| F2 | destination_research skipped when user names a destination | Prompt: call research for any picked destination |
| F3 | itinerary_planner called without full-depth research for all destinations | Prompt: requires full-depth research for all destinations |
| F4 | itinerary_planner called without weather data for all destinations | Prompt: requires weather for all destinations |
| F5 | budget called before research or transport complete | Prompt: call budget after destination research and transport are done |
| F6 | artifact called speculatively (user did not ask to save/export) | Prompt: call artifact only on explicit save/export request |
| F7 | research escalated to full prematurely (no itinerary or artifact requested) | Prompt: escalate to full only before building an itinerary or artifact |
| F8 | destination_research re-called when KnowledgeState already has fresh data | Prompt: KnowledgeState accumulates what has already been researched |
| F9 | weather re-called for same destination + date-range already in state | Same |
| F10 | research + weather + transport serialised for a known destination | Prompt: return multiple tool calls when they don't depend on each other's results |
| F11 | weather for multiple destinations serialised instead of parallel | Prompt: weather called for multiple destinations simultaneously |
| F12 | Two destination_research calls issued in the same turn | Prompt: same non-weather tool must run sequentially, one per turn |

---

### Test group A: Specialist selection

**A1 — Explorer NOT called when destination is decided**
```
Input: "I want to plan a trip to Tokyo in June"

Assert: no explorer call in ConversationHistory
Assert: destination_research(destination="Tokyo", ...) IS called
```

**A2 — Explorer IS called when destination is undecided**
```
Input: "I want a beach trip somewhere in South East Asia"

Assert: explorer call in ConversationHistory
Assert: destination_research does NOT appear in the same turn as explorer
```

**A3 — itinerary_planner not called without full research**
```
Precondition: KnowledgeState has only light-depth research for Kyoto, no weather

Input: "Build me an itinerary for Kyoto next March"

Assert: itinerary_planner does NOT appear before destination_research(depth="full")
        and weather("Kyoto", ...) in ConversationHistory
Assert: destination_research("Kyoto", depth="full") IS called
Assert: weather("Kyoto", ...) IS called
```

**A4 — itinerary_planner not called without weather**
```
Precondition: KnowledgeState has full-depth research for Bali, no weather

Input: "Plan my Bali itinerary for August"

Assert: itinerary_planner does NOT precede weather("Bali", ...) in history
Assert: weather("Bali", ...) IS called
```

**A5 — budget not called before research and transport**
```
Precondition: KnowledgeState is empty

Input: "What's the budget for a trip from London to Bangkok?"

Assert: budget does NOT appear before both destination_research("Bangkok", ...)
        AND transportation("London", "Bangkok", ...) in ConversationHistory
```

**A6 — artifact not called speculatively; research called in light mode**
```
Input: "Tell me about Lisbon"

Assert: no artifact call in ConversationHistory
Assert: destination_research(destination="Lisbon", depth="light") IS called
Assert: destination_research(destination="Lisbon", depth="full") does NOT appear
```

**A7 — research depth not escalated prematurely**
```
Precondition: KnowledgeState is empty

Input: "What's Bali like?" (overview request only, no itinerary or document asked for)

Assert: destination_research(destination="Bali", depth="light") IS called
Assert: destination_research(destination="Bali", depth="full") does NOT appear
```

**A8 — research depth escalated before itinerary**
```
Precondition: KnowledgeState has light-depth research for Tokyo, no weather

Input: "Plan a 5-day Tokyo itinerary for September"

Assert: destination_research("Tokyo", depth="full") appears before itinerary_planner in history
Assert: destination_research("Tokyo", depth="light") does NOT appear
        (already in state — escalate directly to full, no re-light)
```

---

### Test group B: KnowledgeState reuse

**B1 — research not re-called when already in state**
```
Precondition: KnowledgeState has full-depth research and weather for Paris

Input: "Can you plan a Paris itinerary?"

Assert: no destination_research("Paris", ...) call in ConversationHistory
Assert: itinerary_planner IS called (using existing state)
```

**B2 — weather not re-called for same destination + date range**
```
Precondition: KnowledgeState has forecast weather for Tokyo, June 2026

Input: "What activities should I plan for Tokyo given the weather?"

Assert: no weather("Tokyo", ...) call in ConversationHistory
```

---

### Test group C: Parallelisation

**C1 — research + weather + transport batched in parallel**
```
Precondition: KnowledgeState is empty

Input: "I'm flying from Singapore to Bali next July for 7 days"

Assert: at least one orchestrator turn contains all three of:
        destination_research("Bali", ...), weather("Bali", ...), transportation("Singapore", "Bali", ...)
        in the same response
```

**C2 — weather for multiple destinations parallelised**
```
Precondition: KnowledgeState is empty

Input: "Get me weather for Tokyo and Kyoto in October"

Assert: weather("Tokyo", ...) and weather("Kyoto", ...) appear in the same turn
```

**C3 — two destination_research calls NOT in the same turn**
```
Precondition: KnowledgeState is empty

Input: "Compare Tokyo and Seoul for a 2-week trip"

Assert: destination_research("Tokyo", ...) and destination_research("Seoul", ...)
        do NOT appear in the same turn
```

**C4 — budget not parallelised with its prerequisites**
```
Precondition: KnowledgeState is empty

Input: "Plan a full trip from London to Tokyo in May, including costs"

Assert: budget does NOT appear in the same turn as destination_research or transportation
```

---

### LLM-as-judge

**Judge prompt**
```
"A travel planning orchestrator received this user message:
   User: '{user_message}'

   KnowledgeState at time of message:
   {knowledge_skeleton}
   (list sections present and absent — e.g.
   'research: Tokyo (full), Bali (light) | weather: Tokyo (Jun 2026) | routes: none | budget: none | itinerary: none')

   The orchestrator issued these tool calls, in order
   (same-turn calls listed together on one line):
   {tool_call_log}

   Evaluate the routing decisions across all of the following:

   1. Specialist selection — were the right specialists called for this request?
      Flag any specialist that should have been called but wasn't, or was called
      unnecessarily. Consider what data was already in KnowledgeState — a
      specialist should not be called when its output is already present and fresh.

   2. Research depth — was depth='light' vs depth='full' chosen correctly?
      Light is appropriate for a first overview; full is required before an
      itinerary or artifact is built. Escalating to full when the user only
      asked for a summary is a failure.

   3. Prerequisite ordering — were specialists called in the correct dependency
      order? Itinerary requires full research + weather for all destinations.
      Budget requires research + transport. Were any out-of-order calls made?

   4. KnowledgeState reuse — were any specialists called when their data was
      already present in the skeleton above? Redundant calls waste turns from
      the 8-turn budget.

   5. Parallelisation — were independent calls batched in the same turn?
      Research + weather + transport are independent for a known destination.
      Weather for multiple destinations can always be parallel. The same
      non-weather specialist must never appear twice in one turn.

   Verdict: PASS or FAIL.
   Critique: if PASS, note any dimension that was only barely adequate.
   If FAIL, identify each routing mistake specifically — name the call
   that was wrong, redundant, missing, or misordered."
```

**Scenarios**

| # | User message | KnowledgeState | Primary stress |
|---|---|---|---|
| S1 | "I'm flying from London to Tokyo in September for 10 days" | empty | First-turn routing: research + weather + transport parallel, budget sequential |
| S2 | "Plan a beach trip, I haven't decided where yet" | empty | Explorer-only routing; no research until destination picked |
| S3 | "Build me an itinerary for Kyoto" | light research for Kyoto, no weather | Research escalation + weather prerequisite enforced before itinerary |
| S4 | "What's the weather like in Bangkok and Phuket in December?" | empty | Multi-destination weather parallelisation |
| S5 | "Compare Tokyo and Seoul for a 2-week trip" | empty | Sequential multi-destination research; no premature budget/itinerary |
| S6 | "What are the best things to do in Lisbon?" | full research for Lisbon in state | KnowledgeState reuse — no research re-call |
| S7 | "Can you save my trip plan to a document?" | full research + itinerary for Bali | Artifact triggered by explicit save request only |

**Coverage summary**

| Test | Failure mode guarded | Requires real API |
|---|---|---|
| A1 | F1, F2 — wrong specialist for decided destination | yes (stubbed specialists) |
| A2 | F1 — explorer skipped for undecided destination | yes |
| A3 | F3, F4 — itinerary without prerequisites | yes |
| A4 | F4 — itinerary before weather | yes |
| A5 | F5 — budget before prerequisites | yes |
| A6 | F6, F7 — artifact speculative; premature full escalation on overview request | yes |
| A7 | F7 — premature full escalation (no itinerary/artifact requested) | yes |
| A8 | F3, F7 — correct escalation path | yes |
| B1 | F8 — research re-called unnecessarily | yes (preloaded KnowledgeState) |
| B2 | F9 — weather re-called unnecessarily | yes |
| C1 | F10 — research + weather + transport serialised | yes |
| C2 | F11 — multi-destination weather serialised | yes |
| C3 | F12 — two same-specialist calls in one turn | yes |
| C4 | F5 — budget batched with prerequisites | yes |
| S1–S7 | Holistic routing correctness | yes |

---

## Section 2 — Specialist Interactions

> **Scope per specialist**: argument quality (what values the orchestrator passes) + error handling
> (how the orchestrator responds to non-ok status returns). Re-invocation for Artifact is included
> at the end of the Artifact sub-section.

---

### 2.1 Explorer

#### Argument quality

The orchestrator must pass a **positive-intent rewrite** of the user's request as `query` — all
affirmative signals included, all negative constraints stripped (they reach the specialist via
`user_context`, not the query string).

**Failure modes**

| # | Failure | Signal |
|---|---|---|
| F1 | `query` contains negations ("not", "avoid", "no X") | Prompt: omit negations from query entirely |
| F2 | `query` is a verbatim copy of the raw user message instead of a rewrite | Prompt: rewrite in clean, affirmative terms |
| F3 | `query` drops positive geography or activity signals present in the user's message | Prompt: include all relevant positive signals |

**E1 — negations stripped from query**
```
Input: "I want a nature trip in South East Asia, not too heavy on nightlife"

Assert: explorer(query=...) is called
Assert: query does not contain any of: "not", "avoid", "nightlife"
Assert: query contains "South East Asia" and "nature"
```

**E2 — query is a rewrite, not the raw message**
```
Input: "looking for somewhere relaxing, beach vibes, budget-friendly, SE Asia ideally,
        nothing too touristy"

Assert: explorer(query=...) query string is NOT identical to the user message
Assert: query contains "beach", "budget" and "South East Asia" (or "SE Asia")
Assert: query does not contain "touristy"
```

**E3 — positive signals preserved**
```
UserContext: "cultural trip, Japan or South Korea, cherry blossom season, solo traveller"
Input: "Find me some options" (query is implicit from context)

Assert: explorer query contains at least two of: "cultural", "Japan", "South Korea",
        "cherry blossom", "solo"
```

#### Error handling

**E4 — no retry on hard specialist failure**
```
Setup: ExplorerWrapperTool returns {"status": "error", "summary": "ExplorerSpecialist failed: API key invalid"}
       (hard failure — not a transient timeout or rate limit)

Assert: no further tool calls appear in ConversationHistory after the error return
```

**E5 — no destination_research after zero candidates**
```
Setup: ExplorerWrapperTool returns {"status": "ok", "summary": "Found 0 candidates:"}

Assert: no destination_research call appears in ConversationHistory
```

---

### 2.2 Weather

#### Argument quality

**Failure modes**

| # | Failure | Signal |
|---|---|---|
| F1 | `destination` is a region/state/country instead of a specific city | Weather geocodes a point; region names are ambiguous or fail entirely |
| F2 | `date_range` is too vague when user supplied specific dates | Vague range → climate mode when forecast was appropriate |
| F3 | Weather called only for the first city in a multi-city trip | Each destination needs its own weather call |

**W1 — city-level destination passed, not region**
```
Precondition: KnowledgeState has full research for Sikkim with notable areas
              listing Gangtok and Lachung as itinerary stops

Input: "Get weather for my Sikkim trip in April"

Assert: at least one weather call uses "Gangtok" (or "Gangtok, Sikkim")
Assert: at least one weather call uses "Lachung" (or "Lachung, Sikkim")
Assert: no weather call uses destination="Sikkim"
```

**W2 — specific date_range passed when user provides exact dates**
```
Input: "Plan my trip to Bali from June 20 to June 30 2026"

Assert: weather(destination="Bali", date_range=...) is called
Assert: date_range argument contains "2026-06-20" or "June 20"
        — not a month-only string like "June 2026"
```

**W3 — weather called for every city in a multi-city trip**
```
Precondition: KnowledgeState is empty

Input: "I'm visiting Tokyo and Kyoto in October for 2 weeks"

Assert: weather(destination="Tokyo", ...) appears in ConversationHistory
Assert: weather(destination="Kyoto", ...) appears in ConversationHistory
```

#### Error handling

**W4 — retry uses a different destination string after geocode failure**
```
Setup: first weather call returns
       {"status": "error", "summary": "WeatherSpecialist failed: could not geocode 'Pai'"}

Assert: if a second weather call is made for the same city,
        its destination argument differs from "Pai"
        (e.g. "Pai, Thailand" or a nearby city — not an identical retry)
```

**W5 — geocode failure for one city does not block weather for others**
```
Precondition: planning a Chiang Mai + Pai trip

Setup: weather("Pai", ...) returns {"status": "error", ...}

Assert: weather("Chiang Mai", ...) IS called regardless of the Pai failure
```

---

### 2.3 DestinationResearch

#### Argument quality

Research operates at the destination entity level — a region, island, or city that the user
thinks of as a single travel unit. This is the **opposite** of weather/transport, which need
the specific city to geocode or route correctly.

**Failure modes**

| # | Failure | Signal |
|---|---|---|
| F1 | `destination` is a sub-city (e.g. "Gangtok" when user said "Sikkim") | Research should cover the destination as a whole, not one stop within it |
| F2 | destination name differs between research call and subsequent specialist calls | ItineraryPlannerWrapper looks up research by exact string — mismatch causes a pre-check failure |
| F3 | orchestrator proceeds to itinerary or budget after a research failure | Downstream specialists require research to be present |

**R1 — destination at region/entity level, not sub-city**
```
Input: "I want to plan a trip to Sikkim in April"

Assert: destination_research(destination="Sikkim", ...) IS called
Assert: no destination_research call uses destination="Gangtok"
        or any other sub-city of Sikkim
```

**R2 — destination name consistent across all specialist calls**
```
Input: "Plan a full trip to Bali in July including itinerary"

Let research_dest = the destination string in the destination_research call

Assert: itinerary_planner(destinations=[...]) contains exactly research_dest
Assert: budget call uses research_dest as destination
        (no mixing of "Bali", "Bali, Indonesia", "Bali Island", etc.)
```

#### Error handling

**R3 — no itinerary or budget call after research failure**
```
Setup: DestinationResearchWrapperTool returns {"status": "error", ...}

Assert: no itinerary_planner call appears in ConversationHistory
Assert: no budget call appears in ConversationHistory
Assert: no further destination_research call appears
        (hard failure — not retried with same arguments)
```

---

### 2.4 Transportation

#### Argument quality

**Failure modes**

| # | Failure | Signal |
|---|---|---|
| F1 | `trip_type="round_trip"` used for a leg of a multi-city itinerary | Prompt: every leg of a multi-city itinerary gets trip_type="one_way" |
| F2 | `trip_type="one_way"` used for a simple A→B→A return trip | Prompt: round_trip only when this leg has a return flight back to the same origin |
| F3 | `destination` is a region rather than a specific city | Transport needs a routeable city to resolve IATA codes and transfers |
| F4 | Reverse leg looked up separately when outbound was ground-only | Prompt: non-flight ground options are symmetric |

**T1 — round_trip for simple A→B→A**
```
Input: "I'm flying from Mumbai to Tokyo and back, 2 weeks in June"

Assert: exactly one transportation call in ConversationHistory
Assert: that call has trip_type="round_trip"
Assert: no separate transportation("Tokyo", "Mumbai", ...) call appears
```

**T2 — one_way for every leg of a multi-city trip**
```
Input: "Fly London to Tokyo, then Tokyo to Bangkok, then Bangkok back to London"

Assert: transportation("London", "Tokyo", trip_type="one_way") IS called
Assert: transportation("Tokyo", "Bangkok", trip_type="one_way") IS called
Assert: transportation("Bangkok", "London", trip_type="one_way") IS called
Assert: no transportation call uses trip_type="round_trip"
```

**T3 — city-level origin/destination, not region**
```
Input: "I'm travelling to Sikkim from Kolkata"

Assert: transportation call uses a specific city for the destination
        (e.g. "Gangtok" or "Gangtok, Sikkim") — not "Sikkim"
```

**T4 — no reverse ground leg when outbound is ground-only**
```
Precondition: KnowledgeState has ground transport only (bus) for Chiang Mai → Pai

Input: "How do I get from Pai back to Chiang Mai?"

Assert: no transportation("Pai", "Chiang Mai", ...) call in ConversationHistory
```

#### Error handling

**T5 — route not found: itinerary not called, no identical retry**
```
Setup: TransportationWrapperTool returns
       {"status": "failed", "summary": "Could not find a complete path from X to Y after 2 attempts.",
        "partial_summary": "London → Dubai: flight $450"}

Assert: no itinerary_planner call appears in ConversationHistory
Assert: no transportation call with identical arguments appears after the failure
```

---

### 2.5 Budget

#### Argument quality

The `query` is a free-form trip configuration string. It must capture everything the budget
specialist needs to calculate costs: traveller count, duration, accommodation tier, home
currency, and origin city (for flights). Route cost data is injected automatically from
KnowledgeState via `_build_context`, but the narrative config must come from the query.

**Failure modes**

| # | Failure | Signal |
|---|---|---|
| F1 | traveller count or trip duration absent from both query and UserContext | Specialist cannot calculate per-person or per-night costs |
| F2 | accommodation tier absent from both query and UserContext when user stated one | Tier drives the largest cost variance; defaulting silently skews the estimate |
| F3 | home currency or budget target absent from both query and UserContext when user stated one | Specialist cannot convert or validate against user's budget |
| F4 | `destination` string does not match the key used in destination_research | KnowledgeState lookup fails silently — specialist gets no existing cost data |

**BU1 — traveller count and duration present in query or UserContext**
```
Input: "What's the budget for 2 people, 10 days in Tokyo in August?"
       (first message — UserContext not yet populated)

Assert: budget(query=...) is called
Assert: budget query OR UserContext contains traveller count ("2 people" or equivalent)
Assert: budget query OR UserContext contains duration ("10 days" or "10 nights")
```

**BU2 — accommodation tier present in query or UserContext**
```
UserContext already populated: "mid-range traveller, Tokyo August 2026"

Input: "Calculate my trip budget"

Assert: budget query OR UserContext contains the accommodation tier
        ("mid-range" or equivalent)
```

**BU3 — home currency and budget target present in query or UserContext**
```
UserContext already populated: "budget ₹2.5L/person, flying from Mumbai"

Input: "Can we do this trip within budget?"

Assert: budget query OR UserContext contains the origin city ("Mumbai")
Assert: budget query OR UserContext contains the budget figure ("2.5L" or "₹" or "INR")
```

**BU4 — destination matches the research key**
```
Precondition: destination_research("Tokyo", ...) was called earlier in the session

Assert: budget(destination="Tokyo") uses the exact same string
        (not "Tokyo, Japan", "tokyo", or any other variant)
```

#### Error handling

**BU5 — hard failure: no identical retry**
```
Setup: BudgetWrapperTool returns {"status": "error", ...}

Assert: no budget call with identical arguments appears after the failure
```

---

### 2.6 ItineraryPlanner

#### Argument quality

**Failure modes**

| # | Failure | Signal |
|---|---|---|
| F1 | `destinations` list is not in travel order | ItineraryPlanner builds days sequentially — wrong order produces an incoherent route |
| F2 | A city in the trip is omitted from `destinations` | That city gets no itinerary days |
| F3 | `destinations` strings do not match the keys used in destination_research | Wrapper pre-check fails: `_missing_full_research` looks up by exact string |
| F4 | `query` omits arrival date or per-destination duration | Planner cannot assign days or mark arrival/departure day types correctly |

**IP1 — destinations list is in travel order**
```
Input: "I'm flying into Tokyo, spending 7 days there, then 3 days in Kyoto before flying home"

Assert: itinerary_planner(destinations=[...]) is called
Assert: "Tokyo" appears before "Kyoto" in the destinations list
```

**IP2 — all cities present in destinations**
```
Input: "Plan my Tokyo → Kyoto → Osaka trip for 2 weeks"

Assert: itinerary_planner destinations contains "Tokyo", "Kyoto", and "Osaka"
Assert: no destination from the user's trip is absent from the list
```

**IP3 — destination names match research keys**
```
Precondition: destination_research("Bali", depth="full") was called earlier

Assert: itinerary_planner destinations contains exactly "Bali"
        (not "Bali, Indonesia", "Denpasar", or any other variant)
```

**IP4 — query includes arrival date and duration**
```
Input: "Build my Tokyo itinerary, arriving June 20, 7 days"

Assert: itinerary_planner query contains arrival date ("June 20" or "2026-06-20")
Assert: itinerary_planner query contains duration ("7 days" or equivalent)
```

#### Error handling

**IP5 — missing research error triggers escalation then re-invocation**
```
Precondition: KnowledgeState has light-depth research for Kyoto

Setup: itinerary_planner is called; wrapper returns
       {"status": "error", "summary": "Missing or incomplete: Kyoto. Call DestinationResearchSpecialist with depth='full' first."}

Assert: destination_research("Kyoto", depth="full") IS called after the error
Assert: itinerary_planner IS called again after research completes
```

**IP6 — hard specialist failure: no identical retry**
```
Setup: ItineraryPlannerWrapperTool returns
       {"status": "error", "summary": "ItineraryPlannerSpecialist failed: ..."}

Assert: no itinerary_planner call with identical arguments appears after the failure
```

---

### 2.7 Artifact

#### Argument quality

**Failure modes**

| # | Failure | Signal |
|---|---|---|
| F1 | `query` drops document requirements stated by the user | Artifact specialist uses query to determine which sections are required — losing "with budget" means no budget section check |
| F2 | All gaps in needs_data not resolved before re-invoking artifact | Re-invocation with unresolved gaps wastes a turn and returns needs_data again |
| F3 | Artifact re-invoked with a query that drops requirements from the original | The request hasn't changed — dropping a requirement on re-invocation may cause the specialist to omit a section |
| F4 | Artifact re-invoked indefinitely when gaps cannot be filled | Orchestrator must recognise when a gap is unresolvable and surface it to the user |

**AR1 — query preserves document requirements**
```
Input: "Generate a full travel document for my Tokyo trip with budget breakdown and day-by-day itinerary"

Assert: artifact(query=...) is called
Assert: query contains at least one of: "budget", "cost", "costs", "breakdown"
Assert: query contains at least one of: "itinerary", "day-by-day", "schedule", "daily"
```

> General requirement-preservation (for varied phrasings and multi-section documents) is
> evaluated by the Section 2 judge — keyword checks only work when the requirements are known
> upfront in the test fixture.

**AR2 — all needs_data gaps resolved before re-invocation**
```
Setup: artifact returns
       {"status": "needs_data", "summary":
        "Cannot generate artifact — missing required data:\n
         - full-depth research for Kyoto\n
         - day-by-day itinerary for Kyoto\n
         Gather this data first, then call artifact again."}

Assert: destination_research("Kyoto", depth="full") IS called after needs_data
Assert: itinerary_planner IS called after research completes
Assert: artifact is NOT re-invoked until both gaps have been addressed
        (no artifact call between the needs_data return and the itinerary_planner completion)
```

**AR3 — re-invocation preserves requirements from the original query**
```
Continuing from AR2 scenario (original requirements: budget + itinerary):

Assert: the second artifact(query=...) call contains at least one of: "budget", "cost", "costs", "breakdown"
Assert: the second artifact(query=...) call contains at least one of: "itinerary", "day-by-day", "schedule", "daily"
```

**AR4 — artifact not re-invoked after hard failure**
```
Setup: ArtifactWrapperTool returns {"status": "error", ...}

Assert: no artifact call with identical arguments appears after the failure
```

---

### Section 2 — LLM-as-judge

One judge prompt across all Section 2 scenarios. The judge evaluates argument quality and
error handling across all specialists in a single end-to-end flow. It does **not** re-evaluate
routing decisions (covered in Section 1) or response quality (covered in Section 5).
`update_user_context` calls are ignored entirely.

---

**Judge prompt**
```
You are evaluating a travel planning orchestrator's specialist interactions.

## Tool reference

The orchestrator has access to these specialist tools:

- explorer(query, max_results=5)
  query: positive-intent rewrite of user's travel intent — all affirmative signals
  included, ALL negations stripped (negatives are conveyed separately via user_context).

- weather(destination, date_range)
  destination: a specific geocodable CITY name — not a region, state, or country.
  date_range: should match the user's actual travel dates; specific ISO ranges when
  dates are known, vague strings only when dates are genuinely unknown.

- destination_research(destination, depth)
  destination: the destination ENTITY as the user thinks of it — a region, island, or
  named area (e.g. "Sikkim", "Bali", "Kyoto"). Not a sub-city within it.
  depth: "light" for overview/shortlisting; "full" before itinerary or artifact.

- transportation(origin, destination, date_range, trip_type)
  origin/destination: specific CITY names — not regions or airports.
  trip_type: "round_trip" ONLY when this leg is A→B with a return flight to the same
  origin (simple holiday). Every leg of a multi-city itinerary must use "one_way".

- budget(query, destination)
  query: free-form trip config — must include traveller count, duration, accommodation
  tier, home currency/budget target, and origin city (for flights) unless these are
  already captured in UserContext (injected automatically as context to the specialist).
  destination: must exactly match the string used in the destination_research call —
  KnowledgeState lookup is by exact string.

- itinerary_planner(query, destinations)
  query: must include arrival date and per-destination duration.
  destinations: ordered list in travel order; each string must exactly match the
  corresponding destination_research call — the wrapper checks research presence by
  exact string lookup.

- artifact(query)
  query: must preserve all document section requirements the user stated
  (e.g. "with budget" must not be dropped). May be enriched with destination names
  or specialist terminology, but must not lose requirements.
  On re-invocation after needs_data: all listed gaps must be resolved first; the
  re-invocation query must still contain all original requirements.

## Key interdependencies

- destination_research uses region-level names; weather and transportation use
  city-level names. These will legitimately differ for region destinations
  (e.g. research="Sikkim", weather="Gangtok").
- budget(destination) and itinerary_planner(destinations) must use the same strings
  as destination_research(destination) — not weather/transport city strings.
- Ground-only transport options (bus, ferry, taxi) are symmetric — if the outbound
  leg is ground-only, no reverse lookup is needed.

## What to evaluate

You are given the full tool call log for one orchestrator session below.
Ignore all update_user_context calls — do not evaluate them.
Do NOT re-evaluate routing decisions (which specialists were called or in what order)
— focus only on the ARGUMENTS passed to each specialist and how errors were handled.

Evaluate each of the following:

1. Explorer query — are negations absent? Are all positive signals from the user's
   intent present (geography, activity type, travel style, budget tier)?

2. Weather arguments — is each destination a specific city (not region/country)?
   Does date_range match the user's actual travel dates? Is weather called for every
   city in a multi-city trip?

3. DestinationResearch arguments — is each destination at the right entity level
   (region/island/named area, not sub-city)? Is the destination string consistent
   with what budget and itinerary_planner use?

4. Transportation arguments — is trip_type correct (round_trip for A→B→A only,
   one_way for every multi-city leg)? Are origin/destination specific cities?
   Was a reverse leg looked up when the outbound was already confirmed as ground-only?

5. Budget arguments — does the query (or UserContext) contain the trip config needed
   for accurate calculation: traveller count, duration, accommodation tier, home
   currency/budget target, origin city? Does destination match the research key?

6. ItineraryPlanner arguments — are destinations in travel order and complete?
   Do destination strings exactly match the research calls? Does query include
   arrival date and per-destination duration?

7. Artifact arguments and re-invocation — does the query preserve all document
   requirements? If needs_data was returned: were all listed gaps resolved before
   re-invocation? Does the re-invocation query still contain all original requirements?

8. Error handling — for any non-ok status return:
   - Hard errors (invalid credentials, resource not found, specialist logic failure)
     should NOT be retried — identical retry calls are a failure.
   - Transient errors (rate limit, timeout, temporary network failure) SHOULD be
     retried — absence of a retry is a failure.
   - In either case, a downstream specialist that depends on the failed one must not
     be called as if the failure did not occur.

Verdict: PASS or FAIL.
Critique: if PASS, note any argument that was only marginally adequate.
If FAIL, identify each issue specifically — name the tool call, the argument,
and what was wrong or missing.
```

---

**Scenarios**

| # | Trip | Key stresses |
|---|---|---|
| S1 | London → Tokyo round trip, 10 days June, mid-range, user wants itinerary + full document | trip_type=round_trip, budget query completeness, artifact requirements preserved |
| S2 | Tokyo → Kyoto → Osaka, 2 weeks, cultural focus, no document | trip_type=one_way per leg, destinations ordered and complete in itinerary_planner |
| S3 | Sikkim trip, April, cultural and nature, itinerary requested | Region vs city-level split: research="Sikkim", weather/transport="Gangtok"/"Lachung" |
| S4 | Bali trip, artifact requested; ArtifactWrapper **stubbed** to return needs_data (missing itinerary) on the first call, then succeed on the second | All gaps filled before re-invocation; requirements preserved in second artifact call. Stub ensures the re-invocation path is exercised regardless of whether the orchestrator would have proactively filled the gap. |
| S5 | Bangkok trip, weather specialist fails for "Koh Samui" (geocode error) | Retry uses different city string; Koh Samui failure does not block Bangkok weather |

---

## Section 3 — Clarification Behaviour

The orchestrator asks only for gaps that would materially change which specialists are called.
When a gap is asked and the user still doesn't provide the answer, the orchestrator falls back
gracefully rather than stalling. The degradation model:

| Gap | Ask first? | If user refuses / doesn't answer |
|---|---|---|
| No destination (truly unknown) | Yes — hard block | Re-ask; cannot proceed to research/weather/transport/budget/itinerary |
| No approximate dates | Yes | Skip weather and transportation; proceed with research |
| No trip duration | Yes | Assume a reasonable duration (e.g. 7 days); proceed with itinerary |
| No origin city | Yes | Skip transportation; proceed with everything else |
| No passport (visa query only) | Yes | Skip visa details; proceed with general research |
| Budget tier | No | Not asked — proceed covering all tiers |
| Number of travellers | No | Not asked — assume 1 |
| Accommodation type, trip purpose, dietary restrictions | No | Not asked — enrich if present, ignore if absent |

All gaps must be batched into a single question. After a gap is resisted, apply the fallback —
don't re-ask an indefinitely refused non-hard-block gap more than once.

### Failure modes

| # | Failure | Signal |
|---|---|---|
| F1 | Clarification asked when all blocking info is present | Once you have enough to act meaningfully, proceed |
| F2 | Blocking gap not asked before proceeding | Ask for missing info that would materially change specialist calls |
| F3 | Gaps asked across multiple messages instead of batched | Ask all gaps in a single message |
| F4 | Specialist tool calls made in same response as a clarification question | Ask first, then act |
| F5 | Budget tier, traveller count, or accommodation type treated as blocking | Not blocking — proceed without asking |
| F6 | Passport asked when no visa query was raised | Only needed for explicit visa questions |
| F7 | User refuses dates → orchestrator also skips research | Only weather and transport are skipped; research proceeds |
| F8 | User refuses origin city → orchestrator skips more than transport | Only transportation is skipped |
| F9 | User refuses duration → orchestrator blocks itinerary instead of assuming | Assume a duration and proceed |
| F10 | Hard-block gap (no destination) is silently dropped | Re-ask; cannot route without destination |

---

### Test group A: When to ask

**CL1 — no clarification when all blocking info is present**
```
Input: "I want to go to Tokyo in June for 7 days, flying from London"

Assert: tool calls appear in ConversationHistory
```

**CL2 — no specialist calls when intent is too sparse even for explorer**
```
Input: "I want to plan a trip"
(no region, no activity, no travel style — not enough to form an explorer query)

Assert: no specialist tool calls in the orchestrator response
        (update_user_context is permitted)
```

**CL3 — no itinerary or weather call when dates and duration are missing**
```
Precondition: KnowledgeState is empty

Input: "Build me an itinerary for Kyoto" (no dates or duration anywhere)

Assert: no itinerary_planner call in ConversationHistory
Assert: no weather call in ConversationHistory
Assert: no specialist tool calls in the orchestrator's first response
        (update_user_context is permitted)
```

**CL4 — no transport call when origin city is missing**
```
Input: "I'm going to Bangkok in October for 10 days"
(no origin city in message or UserContext)

Assert: no transportation call in ConversationHistory
Assert: no specialist tool calls in the orchestrator response
        (update_user_context is permitted)
```

**CL5 — no destination_research call before passport provided for visa query**
```
Input: "Do I need a visa for Japan?"
(no passport country in UserContext)

Assert: no specialist tool calls in the orchestrator's first response
        (update_user_context is permitted)
```

**CL6 — passport NOT asked for general research**
```
Input: "Tell me about Japan"

Assert: no question about passport or nationality in ConversationHistory
Assert: destination_research IS called
```

**CL7 — budget tier not asked; research proceeds for all tiers**
```
Input: "I want to visit Bali in August for 10 days flying from Sydney"
(budget tier unknown)

Assert: orchestrator makes tool calls without asking about budget tier
```

**CL8 — traveller count not blocking**
```
Input: "Plan a Tokyo trip in June for 7 days flying from London"
(traveller count not stated)

Assert: orchestrator makes tool calls without asking about traveller count
```

---

### Test group B: Batching and multi-turn behaviour

**CL9 — no tool calls in the same response as a clarification question**
```
For any orchestrator response that contains a question to the user:

Assert: that response contains no tool calls
```

**CL10 — no specialist calls while blocking gap remains unanswered**
```
Multi-turn:
  User turn 1: "Plan a trip"
  Orchestrator: responds with no specialist calls
  User turn 2: "Somewhere relaxing" (destination still unresolved)

Assert: no specialist tool calls after turn 2 either
        (destination still unknown — orchestrator must not proceed)
```

**CL11 — unanswered non-blocking gap: proceed with assumption**
```
Multi-turn:
  User turn 1: "Plan a 10-day Tokyo trip in September flying from Mumbai"
  Orchestrator: asks about traveller count or budget tier
  User turn 2: "Just go ahead"

Assert: orchestrator makes tool calls after turn 2 without re-asking
```

---

### Test group C: Fallback behaviour when gaps are refused

**CL12 — user refuses dates: research proceeds, weather and transport skipped**
```
Multi-turn:
  User turn 1: "Plan a trip to Kyoto"
  Orchestrator: asks for dates
  User turn 2: "I don't have dates yet, just start planning"

Assert: destination_research("Kyoto", ...) IS called
Assert: no weather call in ConversationHistory
Assert: no transportation call in ConversationHistory
```

**CL13 — user refuses origin city: transport skipped, everything else proceeds**
```
Multi-turn:
  User turn 1: "Plan a trip to Bangkok in October for 10 days"
  Orchestrator: asks for origin city
  User turn 2: "Don't worry about flights for now"

Assert: no transportation call in ConversationHistory
Assert: destination_research("Bangkok", ...) IS called
Assert: weather("Bangkok", ...) IS called
```

**CL14 — user refuses duration: itinerary proceeds with assumed duration**
```
Multi-turn:
  User turn 1: "Build me an itinerary for Tokyo in June"
  Orchestrator: asks for trip duration
  User turn 2: "Just decide for me"

Assert: itinerary_planner IS called
Assert: itinerary_planner query contains a duration figure
        (orchestrator assumed a value — not left blank)
```

---

### LLM-as-judge

**Judge prompt**
```
A travel planning orchestrator received the following conversation:

{conversation_transcript}
(full multi-turn exchange; mark tool calls inline as [tool: name(args)])

Use this degradation model to evaluate the orchestrator's decisions:

| Gap | Ask first? | Correct fallback if user refuses |
|---|---|---|
| No destination (truly unknown) | Yes | Re-ask; hard block on all research/weather/transport/budget/itinerary |
| No approximate dates | Yes | Skip weather and transport; proceed with research |
| No trip duration | Yes | Assume a reasonable duration; proceed with itinerary |
| No origin city | Yes | Skip transportation only; proceed with everything else |
| No passport (visa query only) | Yes | Skip visa details; proceed with general research |
| Budget tier | No — never ask | N/A |
| Number of travellers | No — never ask | Assume 1 |
| Accommodation type, trip purpose | No — never ask | N/A |

Evaluate the clarification behaviour across all of the following:

1. Correct triggers — did the orchestrator ask only for genuinely blocking gaps?
   Asking about budget tier, traveller count, or accommodation type is always a failure.
   Asking for passport when no visa question was raised is a failure.

2. Batching — when multiple gaps existed, were they all asked in one message?
   Drip-feeding one question per turn is a failure.

3. No premature action — did the orchestrator withhold specialist tool calls while
   waiting for a blocking answer? A specialist call in the same response as a question
   is a failure (update_user_context is permitted).

4. Correct fallback when gaps are refused — did the orchestrator apply the right
   degradation? Skipping too much (e.g. skipping research because dates are missing)
   is as much a failure as skipping too little (e.g. calling transport without an origin).
   Assuming a duration and proceeding is correct; blocking itinerary indefinitely is not.

5. Assumption transparency — whenever the orchestrator proceeds by assuming a missing
   value (e.g. trip duration, traveller count), did it state the assumption in its
   response to the user? Silently assuming without disclosure is a failure.

6. Threshold — once enough information was available to act, did the orchestrator
   proceed rather than seeking more? Over-asking is as much a failure as under-asking.

Verdict: PASS or FAIL.
Critique: if PASS, note any moment where the threshold judgement was marginal.
If FAIL, identify each issue — quote the turn where the wrong decision was made
and explain what the correct behaviour should have been.
```

**Scenarios**

| # | Conversation | Primary stress |
|---|---|---|
| S1 | "Plan a trip" → Orch asks → User answers fully → Orch acts | All gaps batched; no calls before answer; correct triggers only |
| S2 | "I want a warm beach trip in SE Asia, August, 2 weeks" → Orch calls explorer immediately | Enough signal to act — no clarification |
| S3 | "Tokyo, 7 days, June, flying from London" → Orch acts immediately | All blocking info present — no questions at all |
| S4 | "Plan a trip to Kyoto" → Orch asks dates → User: "no dates yet, just start" → Orch calls research but skips weather + transport | Correct fallback: research proceeds, date-dependent specialists skipped |
| S5 | "Plan a trip to Bangkok in Oct for 10 days" → Orch asks origin → User refuses → Orch skips transport, proceeds with research + weather | Correct fallback: only transport skipped |
| S6 | "Build itinerary for Tokyo in June" → Orch asks duration → User: "I don't know" → Orch assumes 7 days and calls itinerary_planner | Correct fallback: assume duration, do not block itinerary |
| S7 | "Do I need a visa for Japan?" → Orch asks passport → User answers → Orch calls research | Passport correctly asked for visa query only |

---

## Section 4 — update_user_context Accuracy

`update_user_context` overwrites the entire `UserContext.context` string, which drives two
downstream mechanisms: the `blocklist` (extracted from explicit negative phrases — used to
hard-exclude candidates and filter explorer queries) and the `wordset` (positive signals —
used for explorer cache relevance scoring). Because it is a full overwrite, each call must
carry the complete accumulated intent, not just the delta from the current turn.

### Failure modes

| # | Failure | Signal |
|---|---|---|
| F1 | Called when user is greeting, thanking, or asking a capability question | Prompt: do NOT call speculatively — these don't warrant a tool call |
| F2 | Called when user asks a follow-up question without providing new trip info | Same |
| F3 | Not called when user explicitly provides destination, dates, preferences, or constraints | Prompt: call first whenever user provides new or revised trip information |
| F4 | Context carries only the current turn's delta, dropping previously stated intent | Each call must be the full accumulated statement — it is a replace, not an append |
| F5 | Negative constraints buried in prose instead of explicit phrases | Prompt: express as "not Thailand", "avoid beaches", "no nightlife" — not buried in prose |
| F6 | Specialist tools called before update_user_context in the same response | Prompt: call update_user_context first, then specialist tools |

---

### Assertion tests

**UC1 — called when user provides trip info**
```
Input: "I want to go to Tokyo in June for 7 days, solo, prefer cultural experiences"

Assert: update_user_context IS called
Assert: update_user_context precedes any specialist tool call in the same response
```

**UC2 — not called for greetings**
```
Input: "Hi!" / "Hello" / "Thanks, that's helpful"

Assert: no update_user_context call in ConversationHistory
```

**UC3 — not called for capability questions**
```
Input: "What can you help me with?" / "What do you do?"

Assert: no update_user_context call in ConversationHistory
```

**UC4 — not called for follow-up questions without new info**
```
Precondition: orchestrator has just returned research results for Tokyo

Input: "Which of those attractions is the most popular?"
(question about returned data — no new destination, dates, preferences, or constraints)

Assert: no update_user_context call in ConversationHistory
```

**UC5 — called before specialist tools in the same turn**
```
Input: "I want to visit Bali in August for 10 days flying from Sydney"

Assert: update_user_context appears before any of
        destination_research / weather / transportation / budget / itinerary_planner
        in ConversationHistory
```

**UC6 — accumulates intent across turns**
```
Multi-turn:
  Turn 1 — User: "I want to go to Tokyo, not interested in nightlife"
  Turn 1 — update_user_context called with: "Tokyo trip, no nightlife"

  Turn 2 — User: "7 days in June, flying from London"
  Turn 2 — update_user_context called

Assert: turn 2 context string contains "Tokyo" (previously stated destination preserved)
Assert: turn 2 context string contains a negation for nightlife
        ("no nightlife", "not nightlife", or "avoid nightlife")
Assert: turn 2 context string contains "June" and ("London" or "flying from London")
```

---

### LLM-as-judge

**Judge prompt**
```
You are evaluating a travel planning orchestrator's use of update_user_context.

The tool overwrites the entire user context on every call — it is a replace, not an append.
Negative constraints must appear as explicit phrases ("not Thailand", "avoid beaches",
"no nightlife") so they are correctly extracted into the blocklist that gates candidate
filtering and explorer queries. Burying them in prose ("I'd rather not go somewhere
too touristy") means they will be missed.

Conversation transcript:
{conversation_transcript}
(show full exchange; mark each update_user_context call with its context argument)

Evaluate across all of the following:

1. Call timing — was update_user_context called at the right moments?
   It should be called when the user provides destination, dates, preferences,
   or constraints. It must NOT be called for greetings, thanks, capability questions,
   or follow-up questions that contain no new trip information.

2. Accumulation — does each context string carry the full accumulated intent,
   including everything stated in prior turns? A context that drops a previously
   stated destination or constraint because only new info was written is a failure.

3. Negative constraint format — are negative constraints expressed as explicit
   phrases ("not X", "avoid X", "no X")? A constraint buried in a sentence like
   "the user prefers not to visit crowded places" will not be correctly extracted
   into the blocklist — this is a failure.

4. Completeness — does the context capture all trip signals the user has stated:
   destination, dates, duration, origin, travel style, interests, and constraints?
   Omitting a stated preference is a failure even if it was already in the previous
   context (since this call replaces it).

5. Ordering — when update_user_context and specialist tools appear in the same
   response, does update_user_context come first?

Verdict: PASS or FAIL.
Critique: if PASS, note any context string that was only marginally complete.
If FAIL, quote the specific context string and identify what was wrong or missing.
```

**Scenarios**

| # | Conversation | Primary stress |
|---|---|---|
| S1 | Single turn: full trip info provided → context written once with all details | Completeness, negative constraint format |
| S2 | Multi-turn: destination in turn 1, dates + origin in turn 2 → context in turn 2 must contain both | Accumulation across turns |
| S3 | User says "not Thailand, avoid beaches, no party scene" → context must use explicit phrases | Negative constraint format — not buried in prose |
| S4 | User says "Thanks!" then "What else can you tell me about Tokyo?" → no update_user_context | Not called for thanks or follow-ups without new info |
| S5 | User revises a preference: "actually I prefer mountains over beaches" → context reflects the update, not both old and new | Revision handling — old preference replaced cleanly |

---

## Section 5 — Responding to User

The orchestrator's response is the only thing the user sees. After tool results are in it must
summarise clearly, offer a natural next step, and never expose internal architecture. For
non-travel or unexpected queries it must redirect gracefully.

### Failure modes

| # | Failure | Signal |
|---|---|---|
| F1 | Raw tool output or JSON leak in response | Prompt: do not expose raw tool output or JSON |
| F2 | Internal specialist or class names exposed ("ExplorerSpecialist ran...", "KnowledgeState shows...") | Prompt: never reveal internal reasoning or decision process |
| F3 | No next step offered after delivering substantive results | Prompt: offer a natural next step |
| F4 | Specialist error message copied verbatim into user-facing response | Prompt: summarise what is useful — raw errors are not |
| F5 | Off-topic or non-travel query answered without redirecting | Orchestrator is a travel planner — out-of-scope queries should be declined politely |

---

### Assertion tests

**RS1 — no raw JSON in response**
```
For any orchestrator response following a tool call:

Assert: response does not contain substrings matching tool return patterns such as
        '"status": "ok"', '"status": "error"', '"result":', '"summary":'
```

**RS2 — no internal names in response**
```
For any orchestrator response:

Assert: response does not contain any of:
        "ExplorerSpecialist", "WeatherSpecialist", "DestinationResearchSpecialist",
        "TransportationSpecialist", "BudgetSpecialist", "ItineraryPlannerSpecialist",
        "ArtifactSpecialist", "KnowledgeState", "SimpleReActAgent", "WrapperTool"
```

**RS3 — greeting handled with plain text, no tool calls**
```
Input: "Hi!" / "Hello" / "Hey there"

Assert: no tool calls in ConversationHistory
Assert: response is non-empty
```

**RS4 — capability question handled with plain text, no tool calls**
```
Input: "What can you help me with?" / "What do you do?"

Assert: no tool calls in ConversationHistory
Assert: response is non-empty
```

---

### LLM-as-judge

**Judge prompt**
```
You are evaluating a travel planning orchestrator's user-facing responses.

The orchestrator should:
- Summarise tool results clearly and concisely in Markdown
- Highlight the most useful information, not dump everything returned
- Offer a natural next step after delivering results
- Never expose raw JSON, tool output, specialist names, or internal architecture
- Handle errors by explaining what went wrong in plain language without revealing
  internal details; if a partial result is available, surface it
- Politely decline and redirect non-travel or clearly off-topic queries
- Respond to greetings and capability questions conversationally without tool calls

Conversation transcript:
{conversation_transcript}
(full exchange including tool call results; the evaluator sees raw tool outputs
 to judge whether they were correctly handled — the user only sees the response text)

Evaluate across all of the following:

1. Clarity and usefulness — after tool results are in, does the response present
   the key information in a readable Markdown summary? Does it avoid data-dumping
   every field returned by the tools?

2. Next step — does the response offer a logical follow-on action where one exists?
   (e.g. after research: "Want me to check flights and weather next?"
    after itinerary: "Shall I save this as a document?")
   Omitting a next step when the flow has an obvious continuation is a failure.

3. No internal exposure — does the response ever mention specialist names, class names,
   tool names, KnowledgeState, or internal decision logic? Any such mention is a failure.

4. Error handling — if a specialist returned an error or partial result, does the
   response explain what happened in plain language? Does it avoid copying the raw
   error string? If partial data was returned, is it surfaced rather than silently dropped?

5. Unexpected queries — if the user asked something off-topic or non-travel (e.g.
   "write me a poem", "what's the stock price of Apple"), did the orchestrator
   politely decline and redirect to travel planning? Answering the off-topic query
   in full is a failure.

6. Conversational turns — for greetings, thanks, and capability questions, is the
   response friendly and appropriately brief? An overly long capability description
   or a robotic greeting response are minor failures.

Verdict: PASS or FAIL.
Critique: if PASS, note any response that was only marginally adequate.
If FAIL, quote the specific response and explain what was wrong.
```

**Scenarios**

| # | Setup | Primary stress |
|---|---|---|
| S1 | Research + weather returned for Tokyo → orchestrator summarises and offers next step | Clarity, data selection, next step |
| S2 | Full itinerary returned → orchestrator summarises highlights, offers to save as document | Next step (artifact), avoids dumping all day slots verbatim |
| S3 | ExplorerWrapperTool returns `{"status": "error", "summary": "ExplorerSpecialist failed: API key invalid"}` | Error in plain language, no raw error string, no specialist name exposed |
| S4 | TransportationWrapperTool returns `{"status": "failed", ..., "partial_summary": "London → Dubai: flight $450"}` | Partial result surfaced, next steps suggested despite incomplete route |
| S5 | User: "Hi, what can you do?" | Friendly, brief, no tool calls, accurate capability description |
| S6 | User: "Can you write me a cover letter?" | Politely declined, redirected to travel planning |
