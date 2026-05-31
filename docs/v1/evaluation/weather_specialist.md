# Evaluation Plan — WeatherSpecialist

## What the LLM Does Here

The specialist runs with `max_iterations=2`. The LLM's only job is to decide which tool to call in iteration 1 and what arguments to pass. The WeatherOutput is assembled programmatically from the tool results; the wrapper summary is template-built. There is no LLM-generated prose to evaluate.

This means the entire evaluation surface is the LLM's **tool call decisions**, which are assertable by inspecting `ConversationHistory`.

Two decisions:
1. **Mode selection** — `weather_forecast` vs `climate_summary` based on how far out the dates are
2. **Slice/augment decision** — when existing weather entries are present in the task context, use `slice_weather_range` instead of re-fetching

---

## Failure Modes

| # | Failure | Prompt signal that should prevent it |
|---|---|---|
| F1 | `weather_forecast` called for dates >16 days out | Specialist prompt explains the 16-day cutoff rule |
| F2 | `climate_summary` called for dates ≤16 days | Same rule |
| F3 | Range spanning the 16-day cutoff treated as forecast | Rule says the **full range** must fall within 16 days |
| F4 | `slice_weather_range` not used when a related entry exists in context | Specialist prompt + task context lists existing entries |
| F5 | Slice used when no related entry exists | Same context — LLM should see there's nothing to slice |
| F6 | Existing forecast sliced and combined with fresh climate for a cross-mode extension | Mode rule applies to the full requested range, not per-segment |

---

## Assertion-based Tests

All assertions are verified by inspecting the agent's `ConversationHistory`.

### Test group A: Mode selection

**A1 — Forecast for near-term dates**
```
Input:  city="London", date_range="[today+3 to today+10]"
        (all days fall within 16 days of today)

Assert: `weather_forecast` called, not `climate_summary`
```

**A2 — Climate for far-term dates**
```
Input:  city="Tokyo", date_range="[today+25 to today+32]"
        (all days fall beyond 16 days)

Assert: `climate_summary` called, not `weather_forecast`
```

**A3 — Climate for vague/null dates**
```
Input:  city="Paris", date_range="late June"
        (no specific dates to check against the cutoff)

Assert: `climate_summary` called
```

**A4 — Range straddling the 16-day boundary uses climate**
```
Input:  city="Mumbai", date_range="[today+14 to today+18]"
        (some days within 16, some beyond — full range must qualify for forecast)

Assert: `climate_summary` called, not `weather_forecast`

Why this matters: the failure mode is the LLM checking only the start date
and deciding forecast is fine when the tail of the range falls outside the window.
```

---

### Test group A (continued): Vague date inference

These test whether the specialist correctly resolves natural language date expressions.
Today's date is injected into the task context, so the specialist has a fixed anchor.

**A5 — "Next week" resolves to near-term forecast**
```
Input:  city="London", date_range="next week"

Assert: `weather_forecast` called, not `climate_summary`
Assert: date arguments span 7 days
Assert: start date is no more than 7 days from today

Why this matters: "next week" has no parsed start/end dates in the DateRange,
so a naive prompt would treat it as label-only and fall back to climate mode.
The specialist should use the injected today's date to resolve the expression
and recognise the window is near-term. Climate mode here loses real forecast
precision unnecessarily.
```

**A6 — "Next month" maps to the correct calendar month, climate mode**
```
Input:  city="Tokyo", date_range="next month"

Assert: `climate_summary` called
Assert: month argument corresponds to the next calendar month from today
        (e.g., if today is in May, month = "June")

Why this matters: the full span of any calendar month always extends well
beyond 16 days, so climate is correct. The month argument must reflect the
right calendar month, not just default to the current one.
```

**A7 — "Early July" with no year defaults to next occurrence of July**
```
Input:  city="Paris", date_range="early July"

Assert: `climate_summary` called
Assert: month argument is July
Assert: if today is before July, the call targets the current year's July;
        if today is after July, the call targets next year's July

Why this matters: a year-less month expression is ambiguous. The LLM should
resolve it to the next future occurrence of that month, not the most recent past one.
```

**A8 — "Winter" maps to winter months, climate mode**
```
Input:  city="London", date_range="winter"

Assert: `climate_summary` called (not `weather_forecast`)
Assert: at least one call covers December, January, or February
        (Northern hemisphere default; London anchors the hemisphere)

Note: the specialist may make one call per month (December, January, February)
in parallel, or a single representative call. Either is acceptable. What is
not acceptable: calling only a single non-winter month, or calling `weather_forecast`.
```

---

### Test group B: Slice/augment decision

These require a pre-seeded KnowledgeState so the task context includes existing weather entries.

**B1 — Subset of existing range: slice only**
```
Precondition: task context includes a WeatherOutput entry for
              Paris, "2026-06-20 to 2026-06-30"

Input:  city="Paris", date_range="2026-06-22 to 2026-06-25"

Assert: `slice_weather_range` called
Assert: `weather_forecast` and `climate_summary` NOT called
```

**B2 — Same-mode extension: slice + fresh fetch in parallel**
```
Precondition: task context includes a forecast WeatherOutput for
              London, "[today+3 to today+8]"
              (existing entry is forecast; the extension also stays within 16 days)

Input:  city="London", date_range="[today+3 to today+12]"

Assert: `slice_weather_range` AND `weather_forecast` both called
        in the same iteration (parallel tool calls in one assistant message)
Assert: the fresh fetch covers only the missing days (today+9 to today+12),
        not the full range
```

**B3 — No existing entry: direct fetch, no slice**
```
Precondition: task context has no weather entry for Dubai

Input:  city="Dubai", date_range="2026-06-20 to 2026-06-25"

Assert: `slice_weather_range` NOT called
Assert: `weather_forecast` or `climate_summary` called directly
```

**B4 — Cross-mode extension: discard existing forecast, fetch fresh climate**
```
Precondition: task context includes a forecast WeatherOutput for
              London, "[today+3 to today+10]"
              (existing entry is forecast mode)

Input:  city="London", date_range="[today+3 to today+25]"
        (full range extends beyond 16 days — entire request requires climate mode)

Assert: `climate_summary` called for the full range
Assert: `slice_weather_range` NOT called
        (existing forecast data cannot be reused — mixing modes in one WeatherOutput
        is not permitted; the existing entry is forecast, the new request is climate)

Why this matters: the tempting wrong answer is slice(today+3 to today+10) +
climate_summary(today+11 to today+25). That would produce a mixed-mode WeatherOutput,
which violates the architecture constraint and gives the user inconsistent data.
```

---

## Test Data

**Cities** — chosen for geocoding reliability:

| City | Used in |
|---|---|
| London | A1, A5, A8, B2, B4 |
| Tokyo | A2, A6 |
| Paris | A3, A7, B1 |
| Mumbai | A4 |
| Dubai | B3 |

**Date construction** — always relative to `today` so tests don't expire:

| Scenario | Construction | Expected mode |
|---|---|---|
| Near-term forecast | `today+3` to `today+10` | forecast |
| Far-term climate | `today+25` to `today+32` | climate |
| Boundary straddle | `today+14` to `today+18` | climate |
| "next week" | literal string | forecast (specialist resolves to ~today+2 to today+8) |
| "next month" | literal string | climate (month = next calendar month) |
| "early July" | literal string | climate (month = July, year = next occurrence) |
| "winter" | literal string | climate (months = Dec, Jan, Feb) |

---

## Coverage Summary

| Test | Failure mode guarded | Requires real API |
|---|---|---|
| A1 | F2 — climate used for near-term | yes |
| A2 | F1 — forecast used for far-term | yes |
| A3 | F1 — forecast used for vague dates | yes |
| A4 | F3 — boundary range not fully classified as climate | yes |
| A5 | F1/F2 — "next week" incorrectly treated as label-only → climate | yes |
| A6 | F2 — "next month" wrong month or wrong mode | yes |
| A7 | F2 — "early July" wrong year or wrong mode | yes |
| A8 | F2 — "winter" wrong months or wrong mode | yes |
| B1 | F4 — slice not used on subset request | no (slice only) |
| B2 | F4 — slice not used on same-mode extension | partial (fresh fetch for missing days) |
| B3 | F5 — slice used when no existing entry | yes |
| B4 | F4 + F3 — cross-mode extension incorrectly slices existing forecast | yes (climate) |
