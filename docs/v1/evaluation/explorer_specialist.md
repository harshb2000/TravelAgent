# Evaluation Plan — ExplorerSpecialist

## What the LLM Does Here

The specialist runs with `max_iterations=3`. It has two distinct jobs:

1. **Search formulation** — decides what `web_search` queries to issue and how many rounds to run
2. **Candidate extraction** — from search results, constructs `DestinationCandidate` objects with name, country, vibe_tags, rationale, and source_url

The wrapper handles cache hits, Jaccard scoring, and KnowledgeState writes. The specialist receives a task that may include existing candidates it must not repeat. The query contains only positive intent; negative constraints are passed separately via UserContext.

---

## Failure Modes

| # | Failure | Prompt signal that should prevent it |
|---|---|---|
| F1 | Existing candidates repeated in output | Task context lists them explicitly with "do not suggest these again" |
| F1b | Duplicate destinations within a single output | LLM must deduplicate before returning |
| F2 | Destination matching a negative constraint returned | Negative constraints are present in UserContext; specialist must read both query and context |
| F3 | Candidate returned without a source URL, or with a hallucinated one | Prompt instructs candidates must come from search results |
| F4 | Vague or generic vibe_tags (e.g. "travel", "destination", "nice place") | Tags should reflect what the destination is actually known for |
| F5 | Rationale that could apply to any destination ("great place to visit") | Rationale should explain why this specific place matches this specific query |
| F6 | All candidates are from the same region for a global query | Query breadth should guide search breadth |
| F7 | Only one search issued for a broad, multi-region query | Prompt encourages parallel searches; one call produces thin coverage |

---

## Section 1 — Assertion-based Tests

### Test group A: Output correctness

**A1 — Existing candidates are not repeated**
```
Precondition: task context includes existing_candidates = ["Bali", "Tokyo", "Lisbon"]
              with instruction not to suggest them again

Input:  query="beach destinations in Southeast Asia or Southern Europe", max_results=3

Assert: output contains no candidate whose name matches any in existing_candidates
        (case-insensitive)

Why this matters: on a partial cache hit the specialist is asked to fill only the
gap. Repeating existing candidates gives the user the same shortlist twice.
```

**A2 — Negative constraints from UserContext are not violated**
```
Input:  query="city trips in Europe", max_results=4
        user_context="User wants European cities. Does not want France or Spain."

Assert: output contains no candidate in France or Spain
        (check both candidate.country and candidate.name against the constraint)
```

**A2b — No duplicate destinations within the output**
```
For any valid run:

Assert: no two candidates in the returned list share the same name
        (case-insensitive)

Why this matters: the specialist searches across multiple results and may
encounter the same destination in different sources. Deduplication is the
LLM's responsibility before returning the final list.
```

**A3 — Required fields are populated on all candidates**
```
For any valid run:

Assert for each DestinationCandidate:
  - name is non-empty
  - country is non-empty
  - vibe_tags is a non-empty list
  - rationale is non-empty
  - source_url is non-empty

Note: source_url being non-empty doesn't guarantee it's valid, but an empty
or missing URL is a clear signal the candidate was hallucinated rather than
sourced from search results.
```

---

### Test group B: Search behavior

**B1 — At least one web_search is issued**
```
For any valid run:

Assert: ConversationHistory contains at least one `web_search` tool call

Why this matters: without this, the specialist is generating candidates from
training knowledge alone, not from current web sources.
```

**B2 — Parallel searches used for clearly multi-region queries**
```
Input:  query="beach destinations in Southeast Asia or the Caribbean", max_results=5

Assert: at least one iteration contains multiple `web_search` calls
        in the same assistant message (parallel tool calls)

Why this matters: Southeast Asia and the Caribbean are distinct enough that
a single search produces region-skewed results. The specialist should recognise
this and issue parallel searches rather than serialising them.
Note: this test is intentionally chosen to be an unambiguous case — two named,
geographically separate regions. The prompt leaves parallelism to the LLM's
judgement; this test checks it exercises that judgement when it clearly should.
```

**B3 — No repeated or near-duplicate search queries across iterations**
```
Input:  query="scenic mountain destinations in Europe for hiking", max_results=4

Assert: no two web_search query strings in ConversationHistory are identical
Assert: no two query strings are near-duplicates — defined as sharing >80% of
        their significant words (stop words excluded)

Why this matters: the prompt instructs the specialist never to repeat a similar
query. Redundant searches waste an iteration and dilute candidate diversity.
```


---

## Section 2 — LLM-as-judge Tests

One judge prompt is used across all scenarios. Each scenario is designed to stress a different part of the criteria, but the judge always evaluates the full output. A weak rationale or poor diversity can pull a verdict to FAIL even if the scenario's primary concern is met.

---

**Judge prompt**
```
"A travel agent was given this task:
   Query: '{query}'
   User context: '{user_context}'  (empty string if none)

   It returned these candidates:
   {candidates}

   Evaluate the quality of this result across all of the following:

   1. Relevance — do the candidates genuinely match the query's intent, or are
      any generic popular destinations included regardless of fit?
   2. Rationale quality — does each rationale specifically explain why this
      destination fits this query, or is it generic praise that could apply
      to any destination?
   3. Diversity — do the candidates offer meaningful variety in geography,
      vibe, and experience type, or are they clustered?
   4. Constraint compliance — if the user context contains exclusions, are
      any excluded destinations or destination types present, even in spirit?
      (Skip this criterion if user context has no exclusions.)
   5. Vibe tag accuracy — do the tags reflect what the destination is actually
      known for, or are they vague and interchangeable?

   Verdict: PASS or FAIL.
   A result can fail due to a single severe issue or multiple moderate ones.
   Critique: if PASS, note what was done well and any dimension that was only
   barely adequate. If FAIL, identify each issue specifically — quote rationales
   that are too generic, name candidates that violate constraints or don't fit,
   describe what diversity is missing."
```

---

**Scenarios**

Each scenario feeds the same judge prompt. The "primary stress" column notes which criterion the scenario is most likely to surface, but the verdict is always holistic.

| # | Query | User context | max_results | Primary stress |
|---|---|---|---|---|
| S1 | "destinations known for street food and vibrant markets" | — | 4 | Relevance |
| S2 | "off-the-beaten-path destinations for nature lovers on a tight budget" | — | 4 | Rationale quality |
| S3 | "interesting city destinations in Asia for a first-time traveller" | — | 5 | Diversity |
| S4 | "relaxing destinations" | "User does not want beach holidays or crowded tourist traps." | 4 | Constraint compliance |

---

## Test Data

**Query patterns to use:**

| Query type | Example | Tests |
|---|---|---|
| Activity-led | "destinations known for street food and markets" | S1 |
| Budget + niche | "off-the-beaten-path nature destinations, tight budget" | S2 |
| Multi-region | "beaches in Southeast Asia or the Caribbean" | B2 |
| Open-ended | "interesting Asian cities for first-time travellers" | S3 |
| Constraint-heavy | query="relaxing destinations" + user_context with negations | A2, S4 |
| Partial cache hit | any query, with existing_candidates pre-seeded | A1 |

**Candidate representation for judge prompt:**

Present candidates as a list of `name (country) — vibe_tags — rationale`. Source URLs are not needed for the judge — they are not visible to the traveller and don't affect quality scoring.

---

## Coverage Summary

| Test | Failure mode guarded | Requires real API |
|---|---|---|
| A1 | F1 — existing candidates repeated | yes |
| A2 | F2 — negative constraint violated | yes |
| A2b | F1 — duplicate destinations within output | yes |
| A3 | F3 — missing required fields | yes |
| B1 | F3 — candidates hallucinated without search | yes |
| B2 | F7 — single search for clearly multi-region query | yes |
| B3 | F7 — repeated/similar queries across iterations | yes |
| S1 | F4, F5 — irrelevant candidates, generic rationale | yes |
| S2 | F5 — rationale doesn't connect to query intent | yes |
| S3 | F6 — clustering, low diversity | yes |
| S4 | F2 — spirit of negative constraint violated | yes |
