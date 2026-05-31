# Evaluation Plan — ArtifactSpecialist

## What the LLM Does Here

Given a user document request and a KnowledgeState context skeleton, the specialist must:

1. **Completeness check (Step 0)** — before any tool calls, decide whether the data present in context is sufficient:
   - **Major gap** (entire section absent that the request depends on): output `missing_data` with plain-English descriptions of each gap, and stop.
   - **Minor gap** (field-level absence within otherwise-present data — e.g. activities without `duration_min`, TravelOptions without `operator`): proceed; omit those specific fields silently.
2. **Fetch** — call the relevant compiled tools in parallel for sections the request needs: `get_research_compiled`, `get_budget_compiled`, `get_weather_compiled`, `get_route_compiled`, `get_itinerary`, `get_candidates_compiled`.
3. **Draft + critique** — assemble the document from fetched data only (no own knowledge). Pass the full draft as the `content` argument to `self_critique`. Do not output the draft as a standalone message. Apply the critique to revise.
4. **Write** — call `file_write` and use the returned path as `file_path` in the output.

The wrapper handles footer appending and KnowledgeState reads (via compiled tools). Those are already unit tested.

---

## Failure Modes

| # | Failure | Prompt signal that should prevent it |
|---|---|---|
| F1 | Major gap treated as minor — proceeds to write when a critical section is absent | Prompt: major gap → signal missing_data and stop |
| F2 | Minor gap treated as major — signals missing_data for field-level absence (e.g. missing duration_min) | Prompt: minor gap → proceed, omit those specific fields |
| F3 | Draft output as a standalone message instead of being passed to self_critique | Prompt: embed draft as `content` argument to self_critique, do NOT output it |
| F4 | self_critique skipped — goes straight from fetch to file_write | Prompt: step 2 is always draft + self_critique before writing |
| F5 | Document includes content not sourced from any compiled tool result | Prompt: only include information that came from compiled tool results |
| F6 | Compiled fetches serialised for a multi-section request | Prompt: call relevant compiled tools in parallel |
| F7 | Filename does not follow the convention `{subject}_{YYYY-MM[-DD]}_v{N}.md` | Prompt specifies the filename convention with examples |
| F8 | `file_path` in output does not match the path returned by `file_write` | Prompt: file_path MUST exactly match the path returned by file_write |
| F9 | `missing_data` descriptions are vague — orchestrator cannot act on them | Prompt: describe each gap in plain English naming the destination or section |
| F10 | Fetches sections not needed for the request (e.g. fetches budget for a research-only doc) | Prompt: call the relevant compiled tools — only those the request needs |

---

## Section 1 — Assertion-based Tests

### Test group A: Completeness check

**A1 — Major gap produces missing_data, not a file**
```
Precondition: KnowledgeState has no DestinationResearch for "Kyoto" —
              only a weather entry exists

Input:  query="Write a full travel document for my Kyoto trip"

Assert: output.missing_data is not None and not empty
Assert: output.file_path is None
Assert: at least one item in missing_data contains "Kyoto"
        (description is specific, not generic)
Assert: no file_write call appears in ConversationHistory
        (specialist stopped at Step 0)
```

**A2 — Minor gap proceeds without signalling missing_data**
```
Precondition: KnowledgeState has full-depth research and itinerary for Tokyo;
              some Activity objects have duration_min=None and source_url=None

Input:  query="Generate a trip planning document for Tokyo"

Assert: output.file_path is not None
Assert: output.missing_data is None
Assert: a file_write call appears in ConversationHistory
```

**A3 — missing_data descriptions are specific**
```
Precondition: KnowledgeState has research for Tokyo but no budget data
              and no itinerary

Input:  query="Create a full trip plan with budget and day-by-day schedule for Tokyo"

Assert: output.missing_data contains at least 2 items
Assert: each item contains a destination name or section name
        (e.g. "budget breakdown for Tokyo", "day-by-day itinerary for Tokyo")
        — not a generic string like "missing data" or "incomplete information"
```

---

### Test group B: Iteration pattern

**B1 — self_critique called before file_write**
```
For any run that produces a file (not missing_data):

Assert: ConversationHistory contains a self_critique tool call
Assert: the self_critique call precedes the file_write call in history order
```

**B2 — file_path matches file_write return value**
```
For any run that produces a file:

Assert: the file_path in the output JSON exactly matches the filename
        argument passed to file_write
        (LLM must not fabricate a path)
```

**B3 — Filename follows the naming convention**
```
For any run that produces a file:

Assert: file_path matches the pattern:
        [a-z0-9_]+_\d{4}-\d{2}(-\d{2})?_v\d+\.md
        (subject slug, date YYYY-MM or YYYY-MM-DD, version vN, .md extension)
```

**B4 — Compiled fetches are parallelised for multi-section requests**
```
Input:  query="Write a full trip plan for Tokyo" where KnowledgeState has
        research, budget, weather, and itinerary for Tokyo

Assert: at least one LLM response in ConversationHistory contains multiple
        get_* tool calls in the same message
        (get_research_compiled + get_budget_compiled + get_weather_compiled,
        not three sequential turns)
```

**B5 — Sections marked [up to date] are not re-fetched; [stale] sections are**
```
Precondition: a prior artifact run already called get_research_compiled("Tokyo")
              and get_budget_compiled("Tokyo"), setting stale=False on both.
              The context skeleton now shows:
                Tokyo  [full, research: up to date]
                  destination budget: ~$120–$250/day [up to date]

Input:  a second query requesting a new Tokyo document

Assert: no new get_research_compiled("Tokyo") call appears in this run's history
Assert: no new get_budget_compiled("Tokyo") call appears in this run's history

Inverse — sections marked [stale] ARE re-fetched:
Precondition: after the prior run, DestinationResearchSpecialist is called again
              for Tokyo (sets research.stale=True). Context now shows:
                Tokyo  [full, research: stale]

Assert: get_research_compiled("Tokyo") IS called in the new run

Why this matters: the context skeleton is the LLM's signal for what is current.
Re-fetching [up to date] data wastes an iteration and risks hitting the
max_iterations=3 budget on a document that needs no new lookups.
```

---

## Section 2 — LLM-as-judge Tests

One judge prompt across all scenarios. The judge evaluates document quality and the fetch + write strategy holistically.

---

**Judge prompt**
```
"A travel document specialist was given this request:
   Query: '{query}'

   The following KnowledgeState data was available:
   {knowledge_skeleton}
     (list of sections present: research for X, budget for X, weather for X,
      itinerary for X+Y, routes from A to B — mark absent sections as 'none')

   Tool call log (fetch calls, critique, and write issued, in order):
   {conversation_history}

   It produced this document:
   {document_content}

   Evaluate the quality across all of the following:

   1. Completeness — are all sections the request asked for present in the
      document and substantive? If the request asked for budget and the
      document has no budget section, that is a failure. If a section is
      present but thin (a single sentence where several paragraphs are
      warranted), flag it.

   2. Source fidelity — does the document content appear to come from the
      KnowledgeState data listed above? Flag any claim or figure that
      could not have come from the available data — this suggests the LLM
      added its own knowledge rather than reporting what was fetched.
      Source links should be present where the compiled tools would have
      provided them.

   3. Minor gap handling — if some KnowledgeState fields were absent
      (e.g. activities without duration_min, transport without operator),
      does the document handle this gracefully — omitting those specific
      fields without drawing attention to the gap, rather than leaving
      'unknown' placeholders or flagging them as errors?

   4. Fetch strategy — were the right compiled tools called for this
      request? Were tools called in parallel where possible? Were any
      tools fetched that the document didn't need?

   5. Document polish — is the structure clear and navigable? Are sections
      logically ordered? Is formatting consistent (headings, lists, bold
      labels)? Would a traveller find this document useful as-is, or does
      it read like a data dump?

   Verdict: PASS or FAIL.
   Critique: if PASS, note what was done well and any dimension that was
   only barely adequate. If FAIL, identify each issue specifically —
   quote the section that is missing, the claim that appears fabricated,
   or the tool call that was unnecessary or missing."
```

---

**Scenarios**

| # | Query | KnowledgeState available | Primary stress |
|---|---|---|---|
| S1 | "Write a full trip planning document for my Tokyo solo trip" | Research (full), weather, budget, itinerary | Completeness, source fidelity, parallel fetches |
| S2 | "Create a destination research summary for Kyoto" | Research (full) only — no budget, no itinerary | Fetch selectivity (should not fetch absent sections), minor gap handling |
| S3 | "Generate a trip document for my Tokyo + Kyoto trip" | Research for both, itinerary for both, budget for Tokyo only (Kyoto budget absent) | Major gap detection (missing Kyoto budget) vs minor gap (if user only asked for research + itinerary) |
| S4 | "Write a destination comparison for Bali, Portugal, and Japan" | Candidates for all three, light research only | Candidates tool usage, comparison structure |
| S5 | "Full travel plan for Tokyo — I know some activity durations are missing" | Research (full, some activities lack duration_min), weather, budget, itinerary | Minor gap handling — duration_min absence should not block the document |

---

## Test Data Notes

- **S3 is intentionally ambiguous**: if the query asks for a full trip plan including costs, the missing Kyoto budget is a major gap → missing_data. If the query only asks for an itinerary document, the missing budget is irrelevant. The judge should evaluate whether the major/minor classification matches what the query actually required.
- **Knowledge skeleton for judge prompt**: present as a bullet list of what is and is not present — e.g. `research: Tokyo (full), Kyoto (full) | budget: Tokyo only | weather: Tokyo | itinerary: Tokyo + Kyoto | routes: none`.
- **Tool call log format**: `1. get_research_compiled(destination="Tokyo")  2. get_budget_compiled(destination="Tokyo")  3. self_critique(...)  4. file_write(filename="...")`. Note which calls were parallel (same turn) vs sequential.
- For S2 and S4, present only a subset of the document to the judge (the first 300 words) if the full document is very long — the judge is evaluating structure and source fidelity, not line-by-line content.

---

## Coverage Summary

| Test | Failure mode guarded | Requires real API |
|---|---|---|
| A1 | F1, F9 — major gap not detected, vague description | no (stubbed KnowledgeState) |
| A2 | F2 — minor gap blocks document | no (stubbed KnowledgeState) |
| A3 | F9 — missing_data descriptions too vague | no (stubbed KnowledgeState) |
| B1 | F3, F4 — self_critique skipped or draft output standalone | yes |
| B2 | F8 — file_path fabricated | yes |
| B3 | F7 — filename convention violated | yes |
| B4 | F6 — fetches serialised | yes |
| B5 | F6 — prior fetches repeated unnecessarily | yes (multi-run session) |
| S1 | F5, F6, document quality | yes |
| S2 | F10, F2 — unnecessary fetches, minor gap over-flagged | yes |
| S3 | F1, F2 — major vs minor gap classification | yes |
| S4 | F10 — wrong tools used, comparison structure | yes |
| S5 | F2 — field-level absence should not block | yes |
