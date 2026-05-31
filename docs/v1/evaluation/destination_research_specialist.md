# Evaluation Plan — DestinationResearchSpecialist

## What the LLM Does Here

The specialist's jobs vary by depth mode:

**Light (`max_iterations=1`):** one broad `web_search`, extract vibe, top_attractions, and a summary narrative.

**Full (`max_iterations=4`):** 3–4 targeted `web_search` calls covering safety, visa, festivals, notable_areas, and interest-tailored activities. Also generates the `summary` narrative.

**Upgrade (light→full, `max_iterations=3`):** prior light searches are visible in ConversationHistory. The LLM should issue only the searches needed for the full-depth fields it doesn't yet have, not re-research vibe and attractions from scratch.

The `summary` field is always LLM-generated narrative — the only prose in the output. Everything else is extracted from search results into structured fields.

---

## Failure Modes

| # | Failure | Prompt signal that should prevent it |
|---|---|---|
| F1 | Light depth issues multiple searches | Iteration budget is 1; prompt must use it efficiently |
| F2 | Full depth uses only 1–2 searches, leaving fields empty | Prompt instructs distinct searches for each full-depth topic |
| F3 | Upgrade re-researches vibe/attractions already in history | Specialist sees prior light research in ConversationHistory |
| F4 | visa_complexity populated with generic info when no nationality is known | Prompt defers visa until passport profile is known from user_context |
| F5 | visa_complexity absent when nationality is clearly stated in user_context | Prompt instructs visa to be populated once profile is known |
| F6 | activities not tailored to stated interests | Prompt instructs interest-aware activity selection from user_context |
| F7 | summary is a restatement of structured fields rather than adding context | Prompt instructs summary to cover seasonal nuances, safety caveats, highlights |
| F8 | Light-mode fields (vibe, top_attractions) are as detailed as full-mode | Light is for comparison; brevity is a quality signal, not a gap |

---

## Section 1 — Assertion-based Tests

### Test group A: Search count by depth

**A1 — Light depth issues exactly one search**
```
Input:  destination="Tokyo", depth="light", user_context=""

Assert: ConversationHistory contains exactly 1 `web_search` call
```

**A2 — Full depth (cold) issues 3–4 searches**
```
Input:  destination="Tokyo", depth="full", user_context="Travelling on Indian passport,
        interested in food and temples"

Assert: ConversationHistory contains between 3 and 4 `web_search` calls total
```

**A3 — Upgrade issues fewer searches than a cold full start**
```
Precondition: specialist ConversationHistory already contains a light-depth run
              for the same destination (vibe and top_attractions already researched)

Input:  destination="Tokyo", depth="full" (upgrade call)

Assert: ConversationHistory for this call contains fewer web_search calls
        than a cold full run (i.e., < 3 new searches added)

Why this matters: the LLM has prior light research in context. Repeating those
searches wastes iterations and may produce duplicate or contradictory field values.
```

---

### Test group B: User context sensitivity

**B1 — visa_complexity populated when nationality is in user_context**
```
Input:  destination="Vietnam", depth="full",
        user_context="Travelling on Indian passport"

Assert: DestinationResearch.visa_complexity is not None and not empty
Assert: at least one key in visa_complexity matches "Indian passport" or similar
```

**B2 — visa_complexity absent when no nationality in user_context**
```
Input:  destination="Vietnam", depth="full",
        user_context="Interested in street food and history"
        (no passport or nationality mentioned)

Assert: DestinationResearch.visa_complexity is None or empty dict
```

**B3 — activities non-empty and tailored to interests when stated stated**
```
Input:  destination="Bali", depth="full",
        user_context="Loves surfing and local food experiences"

Assert: DestinationResearch.activities is not None and not empty
Assert: at least one activity has a tag matching "outdoor", "water", "food",
        or a synonym of the stated interests
```

---

### Test group C: Output structure by depth

**C1 — Light fields are present and brief**
```
Input:  destination="Paris", depth="light"

Assert: vibe is non-empty
Assert: top_attractions is a non-empty list with at most 3 items
Assert: summary is non-empty
Assert: safety_summary is None
Assert: visa_complexity is None
Assert: festivals is None
Assert: notable_areas is None
Assert: activities is None
```

**C2 — Full fields are all present and structured correctly**
```
Input:  destination="Paris", depth="full",
        user_context="Travelling on UK passport, interested in art and food"

Assert: vibe, top_attractions, summary are non-empty
Assert: safety_summary is not None
Assert: festivals is not None
Assert: notable_areas is not None and not empty
Assert: each NotableArea entry has a non-empty description and non-empty highlights list
Assert: activities is not None and not empty
Assert: visa_complexity is not None
        (UK passport is a known profile; visa info for France/EU should be populated)
```

---

## Section 2 — LLM-as-judge Tests

One judge prompt used across all scenarios. Each scenario is designed to surface a different part of the criteria, but the judge evaluates all dimensions and the verdict is holistic.

---

**Judge prompt**
```
"A travel research agent was asked to research a destination with the following inputs:
   Destination: '{destination}'
   Depth: '{depth}'
   User context: '{user_context}'  (empty string if none)

   Tool call log (web_search queries issued, in order):
   {conversation_history}

   It produced this research output:
   {research_output}

   Evaluate the quality across all of the following:

   1. Accuracy — does the content reflect real facts about this destination?
      Flag any claim that seems clearly wrong or outdated.

   2. Depth appropriateness — for light depth, is the output concise and
      sufficient for comparison (vibe, top 2–3 attractions, concise summary)?
      For full depth, is every field substantive and non-generic? For notable_areas,
      does each entry describe a meaningful zone with specific highlights, not just
      a single attraction renamed as an area?

   3. Summary quality — does the summary add genuine context beyond the
      structured fields — seasonal nuances, festival timing, destination
      character, or practical nuances a traveller needs? Or is it just a
      prose restatement of what the structured fields already say?

   4. Interest and context alignment — if user context mentions specific
      interests, travel style, or trip type, do the activities and research
      focus reflect those? Or is the output generic regardless of context?

   5. Visa accuracy — if a nationality is present in user context, is the
      visa information correct for that passport at this destination?
      Skip this criterion if no nationality is stated.

   6. Search strategy — were the queries issued well-targeted to the
      information this depth requires? For full depth, did distinct searches
      cover different topics (e.g. visa requirements, safety, festivals,
      notable areas, interest-tailored activities) rather than re-issuing the
      same broad overview query? For an upgrade run, did the searches focus
      only on full-depth gaps — were any queries clearly repeating what a
      prior light run already found (vibe, top attractions)? Were any queries
      generic enough that they would return unhelpful or irrelevant results
      for this specific destination?

   Verdict: PASS or FAIL.
   A result can fail due to a single severe issue (e.g. wrong visa info,
   clearly inaccurate safety summary) or several moderate ones.
   Critique: if PASS, note what was done well and any dimension that was
   only barely adequate. If FAIL, identify each issue specifically — including
   any search queries that were misdirected, redundant, or too generic."
```

---

**Scenarios**

| # | Destination | Depth | User context | Primary stress |
|---|---|---|---|---|
| S1 | Tokyo | light | — | Accuracy + brevity of light output |
| S2 | Bali | full | "Interested in surfing and local food" | Interest alignment, activities |
| S3 | Vietnam | full | "Travelling on Indian passport" | Visa accuracy |
| S4 | Mexico City | full | — | Safety summary quality, summary adds context |
| S5 | Tokyo | full (upgrade) | "Interested in food and temples, UK passport" | Upgrade quality — full adds depth, doesn't repeat light |

---

## Test Data Notes

- **S5 (upgrade)** requires running S1 first on the same specialist instance so the light research is in ConversationHistory before the full call.
- **Visa ground truth for judge:** Vietnamese visa for Indian passport = e-visa required, ~$25, 30-day stay. UK passport for France = visa-free (Schengen). These are stable enough to be used as judge reference facts.
- Present research output to the judge as structured text: each field label followed by its content. Source URLs can be omitted — the judge evaluates content quality, not attribution.
- Present the tool call log as a numbered list of search queries: `1. web_search("query")`. For upgrade scenarios, prefix the light-run queries with "(prior light run)" so the judge can distinguish old from new searches.

---

## Coverage Summary

| Test | Failure mode guarded | Requires real API |
|---|---|---|
| A1 | F1 — light uses multiple searches | yes |
| A2 | F2 — full uses too few searches | yes |
| A3 | F3 — upgrade re-researches known fields | yes (upgrade run) |
| B1 | F5 — visa absent when nationality known | yes |
| B2 | F4 — visa populated without nationality | yes |
| B3 | F6 — activities not interest-tailored | yes |
| C1 | F8 — light fields too detailed or full fields present | yes |
| C2 | F2 — full fields missing | yes |
| S1 | F7, F8 — summary quality, light brevity | yes |
| S2 | F6 — interest alignment | yes |
| S3 | F4, F5 — visa accuracy | yes |
| S4 | F7 — summary adds context, not just restatement | yes |
| S5 | F3 — upgrade wastes searches, adds no depth | yes (upgrade run) |
