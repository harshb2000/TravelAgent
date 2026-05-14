# Architecture Philosophy v1

This document captures the desired capabilities of TravelAgent, the core challenges in building it well, and the design principles that shape the v1 architecture. It is meant to be read before the technical architecture doc — the technical decisions there are grounded here.

---

## Desired Capabilities

1. **Full query spectrum** — Handle everything from "I want to travel somewhere nice" to "Mumbai to Tokyo, June 20–30, budget ₹2.5L" without requiring the user to use any particular format or supply any particular set of fields upfront.

2. **Real data, not hallucinated knowledge** — Every cost estimate, weather reading, flight price, and visa requirement must come from an external source with a timestamp. The agent should never state a fact from training data as if it is current.

3. **Holistic timing reasoning** — Recommending *when* to travel involves more than weather. It requires understanding peak vs. off-peak pricing, destination festivals and events (some to seek, some to avoid), public holidays at the destination, and public holidays at the origin (long weekends worth targeting). These must be considered together.

4. **Multi-destination planning** — The system should be as capable of comparing three cities and producing a multi-leg itinerary as it is of planning a single destination trip. Neither should feel like an edge case.

5. **Minimal resource usage** — Every LLM call and every API call has a cost. The system should complete tasks using the fewest calls that actually produce a useful answer. Broad, speculative searches fired before the user's intent is clear are wasteful and produce lower-quality results.

6. **Provider-agnostic LLM** — No vendor lock-in. The system should work with any OpenAI-compatible endpoint so that the LLM backend can be swapped for cost, latency, or capability reasons without changing application code.

7. **Free-form artifact output** — The final output should be whatever the user finds most useful — a comparison, an itinerary, a packing list, a cost breakdown — not a fixed template imposed by the system.

---

## Core Challenges

### 1. The vague query problem

Most real travel queries are underspecified. "I want to travel somewhere nice" is not actionable — firing web searches or flight lookups at this stage produces noise, not signal. But asking too many clarifying questions before doing anything is equally frustrating. The system needs to distinguish between queries that are ready to act on and queries that need a single targeted clarification round first.

### 2. Context degradation at scale

A simple agent loop that calls tools one at a time accumulates every tool result in its context window. Researching four destinations simultaneously means thousands of tokens of raw flight data, weather readings, and search snippets piling up in one context. By the time the agent tries to reason about the results, the quality of its planning has degraded. The architecture must prevent this by keeping raw data out of the orchestrating context.

### 3. The discovery gap

Tools like flight search and weather forecast require a known destination as input. But queries like "where can I surf?" or "where does my money stretch furthest?" have no destination yet — the answer space itself must be generated. A system that only has point-lookup tools cannot handle this class of query without a dedicated capability for open-ended discovery.

### 4. Sequential vs. parallel tension

Researching multiple destinations should happen in parallel. A naive reactive loop calls one tool, waits for the result, decides what to call next, and so on. This is both slow and wasteful — the agent produces an unnecessarily long chain of LLM calls just to reach a plan it could have written upfront. Planning explicitly before executing makes parallelism a natural consequence.

### 5. Responsibility blur at scale

As the feature set grows, a single agent with all tools becomes hard to tune, debug, and extend. The logic for querying Amadeus flight data has nothing to do with the logic for synthesising a day-by-day itinerary. Mixing them in one agent means that improving one risks breaking the other, and the agent's context is cluttered with tools it does not need for a given subtask.

---

## Design Principles

### Clarify before you act

When a query leaves critical dimensions ambiguous, the first response should be a targeted clarifying question — not a speculative search. The quality of every downstream API call depends on knowing what the user actually wants.

Good clarifying questions eliminate multiple unknowns simultaneously. "Are you looking for something international or closer to home, and roughly what's your budget range?" resolves both scope and budget tier in one exchange. The goal is to reach actionability in one clarification round, not to interrogate the user.

The Orchestrator does *not* clarify when:
- A reasonable default assumption can be made and stated ("I'll assume you're travelling solo")
- The query is specific enough to act on even with missing fields
- Asking would feel pedantic ("where can I surf?" — just answer it)

Clarification rounds have a cost: they delay the user getting to an answer. Clarify only when the ambiguity would cause the system to waste significant resources or produce a result the user clearly didn't want.

### Cheapest path first

Before committing to any external API call, the Orchestrator should evaluate whether the query can be answered more cheaply. From cheapest to most expensive:

1. **Answer from session state** — is the answer already in KnowledgeState from earlier in this conversation?
2. **LLM reasoning alone** — can the Orchestrator synthesise an answer from UserContext and existing knowledge without any new external data?
3. **Single specialist call** — does this need exactly one agent (e.g. weather for a known city and date)?
4. **Multiple parallel specialist calls** — does this require coordinating several agents simultaneously?

Only escalate when the cheaper path genuinely cannot produce a good enough answer. A question like "is this a good time to visit Morocco?" might be answerable with a single WeatherAgent call. It does not need ExplorerAgent, DestinationResearchAgent, TransportationAgent, and BudgetAgent all firing in parallel.

The same ladder applies within research depth. Light research is cheap; full research is expensive. Don't run the expensive version until it's warranted.

### Parallel tool use over serial loops

When a query requires multiple specialists, the Orchestrator calls them in parallel by returning multiple tool_calls in a single LLM response. This avoids the latency of serial execution while preserving the ability to adapt: if the first round of results changes what the Orchestrator needs to know next, it simply calls different specialists in the next iteration. Breadth and sequence are decided turn by turn, not locked in upfront.

### Lazy research, progressive commitment

Do not deep-research a destination until the user shows intent to consider it seriously. Present a shortlist with light research first, then deepen on the option the user engages with. Forcing commitment before data is a bad interaction pattern.

**What light research is sufficient for:**
Light research exists to support comparison and shortlisting. It covers enough to answer "is this place worth considering?" — not "how do I actually go there?":
- Vibe and character (1–2 sentences)
- Budget tier fit (backpacker / mid-range / luxury — broad)
- Climate sketch for the travel window (hot/wet/cool — not a day-by-day forecast)
- Top 2–3 things the destination is known for (names only, no detail)
- Visa complexity tier (easy / on-arrival / requires advance application)

**What light research does not cover — and cannot substitute for:**
- Daily cost breakdown with actual numbers (food, transport, accommodation)
- Full visa requirements (documents, fees, processing time, application process)
- Safety assessment
- Festival and public holiday calendar for the travel window
- Neighbourhood guide
- Activity recommendations tailored to the user's specific interests

Any question that touches these requires full depth. Attempting to answer them from light research produces vague, unreliable output.

**What triggers escalation to full depth:**
1. The user names a destination directly without going through a shortlist — start at full depth from the beginning
2. The user selects or explicitly engages with a destination from a shortlist ("let's go with Tokyo")
3. The user asks a question about a place that light research doesn't cover ("what neighbourhood should I stay in?")
4. An itinerary is requested — impossible to build from light data
5. An artifact is requested — artifact quality depends on full research
6. The user explicitly asks for more detail ("tell me more about Tbilisi")

**Pre-deep clarification — quality booster, not a gate:**
Once a destination is committed and full research is about to run, one optional clarifying question can meaningfully improve the output quality:
- If activity interests are unknown: "Any particular focus — temples and history, food scene, nightlife, or a mix?" shapes what DestinationResearchAgent and ItineraryPlannerAgent search for
- If travel dates are completely absent: "Any rough dates in mind?" lets WeatherAgent run in forecast mode rather than falling back to historical climate averages

This is not a gate. If the user doesn't answer or gives a vague response, the system proceeds with reasonable defaults. The question is only worth asking when the answer would materially change the direction of research — not just marginally refine it. One question maximum.

### Capability-based specialisation

Each specialist agent owns exactly one domain and has exactly the tools that domain requires. Benefits:
- Each agent's system prompt is tightly focused, producing higher-quality outputs
- Adding a new capability (Google Places, hotel search) extends or adds a specialist — it does not touch the Orchestrator or other agents
- Each specialist is independently testable
- The Orchestrator's context stays clean — it sees structured summaries, never raw API payloads

### Graceful degradation, never hard failure

If a specialist returns an error or an API call fails, the system continues with what it has. The Orchestrator notes the gap, uses whatever estimates it can synthesise, labels them clearly ("couldn't fetch live prices — using recent typical range"), and keeps going. Hard failures should only occur when continuing would produce actively misleading output. Uncertainty, labeled as such, is always better than a crash.

---

## What This Architecture Is Not

- **Not a general-purpose agent framework** — the design is specific to the travel planning domain. The specialist set, the state model, and the planning logic are shaped by the problem, not by a desire to be reusable.
- **Not a pipeline** — the sequence of agents is not fixed. The Orchestrator decides at runtime which ones to call, how many iterations to spend, and in what order. A simple factual query might call one specialist once; a full trip plan calls several in parallel across multiple iterations.
