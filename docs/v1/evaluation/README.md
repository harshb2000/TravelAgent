# Evaluation Plan — TravelAgent v1

## Goal

Measure how well each component does its job — not just whether the code runs, but whether the agent makes the right decisions, produces accurate and useful output, and degrades gracefully. Unit tests already cover function correctness; these evaluation plans cover **behavioral correctness**.

---

## Two Test Modes

### 1. Assertion-based

Deterministic checks that don't require a judge model. These verify:
- Which tools the LLM chose to call, and with what arguments (inspected via `ConversationHistory`)
- Structural validity of the LLM's output (required fields, correct types, values that reflect tool results rather than hallucinations)
- Decision correctness (right mode selected, right tool called given the inputs)

Assertion tests can run in CI. They require real or controllable tool calls, but the assertions themselves are boolean — pass or fail.

Programmatic behaviors (wrapper cache hits, KnowledgeState writes, input validation) are already covered by unit tests and are out of scope here.

### 2. LLM-as-judge

Semantic quality checks where the expected output is a range of valid answers, not a single value. The judge model reads the specialist's output and returns a **pass/fail verdict with a critique**:
- On pass: what was done well, and what could still be better
- On fail: specifically why the output is inadequate

These verify things like: content accuracy, completeness, whether adverse information is flagged clearly, and whether distinct inputs produce meaningfully distinct outputs.

Judge tests are slower and have a cost per run. Run them on demand (before a release, after a prompt change, or on a scheduled cadence) rather than in CI.

---

## Evaluation Scope

| Component | Assertion Plan | Judge Plan | Status |
|---|---|---|---|
| WeatherSpecialist | [weather_specialist.md](weather_specialist.md) | — (no LLM-generated output to judge) | Draft |
| ExplorerSpecialist | [explorer_specialist.md](explorer_specialist.md) | [explorer_specialist.md](explorer_specialist.md) | Draft |
| DestinationResearchSpecialist | [destination_research_specialist.md](destination_research_specialist.md) | [destination_research_specialist.md](destination_research_specialist.md) | Draft |
| TransportationSpecialist | [transportation_specialist.md](transportation_specialist.md) | [transportation_specialist.md](transportation_specialist.md) | Draft |
| BudgetSpecialist | [budget_specialist.md](budget_specialist.md) | [budget_specialist.md](budget_specialist.md) | Draft |
| ItineraryPlannerSpecialist | [itinerary_planner_specialist.md](itinerary_planner_specialist.md) | [itinerary_planner_specialist.md](itinerary_planner_specialist.md) | Draft |
| ArtifactSpecialist | [artifact_specialist.md](artifact_specialist.md) | [artifact_specialist.md](artifact_specialist.md) | Draft |
| Orchestrator (routing) | TBD | TBD | — |
| Full system (end-to-end) | TBD | TBD | — |

---

## What These Plans Are Not

- Not performance benchmarks (latency, cost per query)
- Not regression tests for specific API response formats
- Not prompt unit tests (testing a single LLM call in isolation)

These plans test the agent's **decision-making loop** — the sequence of tool calls, caching decisions, mode selections, and output quality that emerge from the full specialist run.

---

## Common Infrastructure Assumptions

All evaluation tests assume:

- A real or controllable `LLMClient` is available (pointing at a test model is fine)
- Real tool clients can be replaced with configurable stubs that return deterministic responses for known inputs
- `KnowledgeState` can be pre-seeded for tests that verify cache/slice behavior
- Conversation history from a specialist run is inspectable (to assert which tools were called and in what order)
- A judge runner is available: a thin wrapper that sends a prompt to an LLM and returns a structured score

Automation design is out of scope for these plans — that discussion follows once all component plans are written.
