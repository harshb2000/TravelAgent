# Evaluation Plan — BudgetSpecialist

## What the LLM Does Here

Given a free-form trip query and KnowledgeState context (existing DestinationBudget data and TravelOption costs), the specialist must:

1. **Decide whether to web_search** — if cost data for any category is missing from context, issue parallel `web_search` calls (accommodation, food, activities, local transport in one iteration). Skip searches if data is already present.
2. **Convert currency** — call `currency_convert` for the home currency rate when a home currency or budget is present in user context.
3. **Use `calculate` for all arithmetic** — per-person splits, party size scaling, range computation, totals. No LLM-side arithmetic.
4. **Exclude `flight/return` TravelOptions** from flight cost totals — round-trip prices cover both legs; counting them once is correct.
5. **Generate the `breakdown` string** — formatted summary showing costs per category, totals in USD and home currency, and delta against stated budget if one exists.

The wrapper handles KnowledgeState writes. Programmatic behavior already unit tested.

---

## Failure Modes

| # | Failure | Prompt signal that should prevent it |
|---|---|---|
| F1 | Arithmetic computed by LLM reasoning instead of `calculate` | Prompt instructs all numeric computation goes through `calculate` |
| F2 | `currency_convert` not called when home currency is known | Prompt instructs conversion when home currency present in context |
| F3 | `flight/return` cost counted twice — once per leg instead of once per purchase | Both outbound and return legs carry the same round-trip `cost_usd`; count it once |
| F4 | Cost category web_searches serialised instead of parallel | Prompt instructs parallel searches for independent categories |
| F6 | Accommodation cost not scaled by party size and nights | Prompt instructs per-room/night scaling using party size from query |
| F7 | Breakdown shows only USD with no home currency equivalent | Prompt instructs dual-currency output when home currency known |
| F8 | Budget delta not shown when user stated a total budget | Prompt instructs comparison against stated budget |

---

## Section 1 — Assertion-based Tests

**A1 — `currency_convert` called when home currency in user context**
```
Input:  query="2 people, 7 nights Tokyo, mid-range",
        user_context includes "budget ₹2.5L" or "home currency INR"

Assert: ConversationHistory contains a `currency_convert` call
Assert: the call converts from USD to INR (or vice versa)
```

**A2 — `currency_convert` not called when no home currency specified**
```
Input:  query="1 person, 5 nights Bali, budget $800"
        (USD budget, no home currency mentioned)

Assert: ConversationHistory contains no `currency_convert` call
```

**A3 — `flight/return` round-trip cost counted once, not twice**
```
Precondition: KnowledgeState context includes two TravelOptions both with
              mode="flight/return", cost_usd=900 (same round-trip total —
              one for the outbound leg, one for the return leg)

Input:  query includes the round-trip route

Assert: the `calculate` expression for flights uses 900, not 1800
Assert: breakdown flight total is $900, not $1800

Why this matters: both legs carry the same price because it's one purchase.
Summing both produces a doubled total. The LLM must recognise that two
flight/return entries for the same round-trip represent one transaction.
```

**A4 — Parallel web_searches when cost data missing**
```
Precondition: KnowledgeState context has no DestinationBudget for the destination

Input:  query="1 person, 5 nights Paris"

Assert: at least one LLM response contains multiple `web_search` calls
        in the same message (accommodation, food, transport, activities)
```


---

## Section 2 — LLM-as-judge Tests

One judge prompt across all scenarios. The judge evaluates breakdown quality holistically.

**Judge prompt**
```
"A budget specialist was asked to produce a trip cost breakdown for:
   Query: '{query}'
   User context: '{user_context}'

   It produced this breakdown:
   {breakdown}

   Evaluate the quality across all of the following:

   1. Arithmetic consistency — do the per-category subtotals add up to
      the stated total? Pick any two numbers and verify the relationship
      makes sense (e.g. nightly rate × nights = accommodation total).

   2. Category completeness — are all relevant cost categories present?
      For a flight trip: flights, accommodation, food, local transport,
      activities. Flag any that are missing without explanation.

   3. Scaling correctness — is accommodation shown per room/night and
      scaled correctly by party size and trip length? Is food shown
      per person and scaled by party size and days?

   4. Currency presentation — if a home currency or budget is mentioned
      in the query or context, are costs shown in both USD and that
      currency? Is the exchange rate stated?

   5. Budget comparison — if a total budget is stated, does the breakdown
      clearly show whether the trip fits within it and by how much?

   Verdict: PASS or FAIL.
   Critique: if PASS, note what was done well and any dimension that was
   only barely adequate. If FAIL, identify each issue specifically —
   quote the number that is wrong or the category that is missing."
```

**Scenarios**

| # | Query | User context | Primary stress |
|---|---|---|---|
| S1 | "1 person, 7 nights Tokyo, mid-range" | "Home currency INR, budget ₹1.5L" | Currency conversion, budget delta |
| S2 | "2 people, 5 nights Bali, budget $1500 total" | — | Party size scaling, USD budget comparison |
| S3 | "1 person, 5 nights Paris, flying from London" | "Home currency GBP" | Flight inclusion, GBP conversion |
| S4 | "2 people, 10 nights: 5 in Tokyo + 5 in Kyoto" | "Home currency INR" | Multi-destination totalling, no double-count |

---

## Coverage Summary

| Test | Failure mode guarded | Requires real API |
|---|---|---|
| A1 | F2 — no currency conversion | yes |
| A2 | F2 inverse — unnecessary conversion | yes |
| A3 | F3 — flight/return double-counted | no (stubbed KnowledgeState) |
| A4 | F4, F5 — searches serialised or missing | yes |
| S1–S4 | F1 — arithmetic correctness (judge criterion 1) | yes |
| S1 | F2, F7, F8 — currency, budget comparison | yes |
| S2 | F6, F8 — party scaling, budget fit | yes |
| S3 | F3, F7 — flight inclusion, currency | yes |
| S4 | F3, F6 — multi-destination, no double-count | yes |
