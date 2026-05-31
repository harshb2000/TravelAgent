# Evaluation Plan — TransportationSpecialist

## What the LLM Does Here

Given one or more city-pair routes, a date range, and a trip type (`"one-way"` or `"round-trip"` passed explicitly by the orchestrator), the specialist must:

1. **Resolve IATA codes** — `web_search` to map city names to airport codes before calling `flight_search`. Codes already resolved in a prior call on the same session should not be looked up again.
2. **Search flights** — call `flight_search` with resolved IATA codes and the provided `trip_type`.
3. **Find ground transfers** — `web_search` for realistic transfer options at the departure and arrival city (taxi, metro, bus, etc.). Ground transfers are reversible — one set of transfer options per city endpoint serves both directions. For a round-trip, do not duplicate ground transfer entries for the return leg.
4. **Construct `TravelOption` objects** — flight legs must use `"<IATA> Airport, <City>"` format for origin/destination; mode must be `"flight/one-way"` for the outbound leg and `"flight/return"` for the return leg.
5. **Cover the full path** — the returned list must contain: departure transfer + outbound flight + arrival transfer. For round-trip, also include the return flight leg. Ground transfers are shared across directions.

The wrapper handles BFS pre-firing, KnowledgeState writes, and summary construction. Those are already unit tested.

---

## Failure Modes

| # | Failure | Prompt signal that should prevent it |
|---|---|---|
| F1 | `flight_search` called with city names instead of IATA codes | Prompt instructs IATA resolution as a prerequisite step |
| F2 | IATA codes re-resolved when already present in ConversationHistory | Prior resolutions are visible in history; prompt instructs skipping re-lookup |
| F3 | Departure or arrival transfer missing from output | Prompt instructs full path coverage: transfer + flight + transfer |
| F4 | Flight `TravelOption` uses city name instead of `"<IATA> Airport, <City>"` for origin/destination | Prompt specifies the enrichment format |
| F5 | Either leg of a round-trip constructed with `mode="flight/one-way"` instead of `"flight/return"` | For round-trips both outbound and return legs use mode="flight/return"; trip_type is passed as input |
| F7 | Multi-airport city searched with only one airport code | Prompt instructs searching all relevant airports for known multi-airport cities |
| F8 | Transfer options are token — only "taxi" with no alternatives | Prompt instructs providing multiple realistic transfer modes with rough costs |
| F9 | Ground transfers duplicated for return leg on a round-trip | Ground transfers are reversible — one entry per city endpoint covers both directions |
| F12 | Both ground transfers placed at the same city endpoint | Reversibility applies within one endpoint; each city still needs its own transfer |
| F10 | IATA code hallucinated for a city with no airport | LLM must recognise no airport exists and route via nearest viable city |
| F11 | Nearest airport city found, but extended ground transfer to actual destination missing | Full path must reach the stated destination, not terminate at the gateway city |

---

## Section 1 — Assertion-based Tests

### Test group A: IATA resolution

**A1 — flight_search includes all relevant airports for a city**
```
Input:  routes=[("Delhi", "Bangkok")], date_range="2026-07-15"
        (Bangkok has two major airports: BKK Suvarnabhumi and DMK Don Mueang)

Assert: flight_search `origin_airports` contains ["DEL"]
Assert: flight_search `destination_airports` contains both "BKK" and "DMK"
```

**A2 — No re-resolution when IATA already in history**
```
Precondition: ConversationHistory already contains a prior call where
              "BOM" was resolved for Mumbai and "NRT" for Tokyo

Input:  routes=[("Mumbai", "Tokyo")], date_range="2026-08-10"
        (same cities, different date — new route lookup needed)

Assert: no new web_search for IATA codes appears in this call's history
Assert: flight_search is called directly with BOM/NRT
```

**A3 — flight_search arguments contain valid IATA codes**
```
Input:  any route involving named cities

Assert: all values in flight_search's `origin_airports` and
        `destination_airports` arguments match the pattern [A-Z]{3}
        (three uppercase letters — no city names, no lowercase)
```

**A4 — Single-airport city uses exactly one code**
```
Input:  routes=[("Singapore", "Dubai")]
        (Singapore: SIN only; Dubai: DXB only)

Assert: flight_search `origin_airports` == ["SIN"]
Assert: flight_search `destination_airports` == ["DXB"]

Why this matters: the inverse of A1 — the LLM should not pad single-airport
cities with spurious codes.
```

**A5 — No-airport destination routes via nearest viable airport**
```
Input:  routes=[("Delhi", "Mahabaleshwar")], date_range="2026-07-15"
        (Mahabaleshwar has no airport; nearest options are Pune PNQ ~120km
        or Mumbai BOM ~250km)

Assert: flight_search destination_airports contains PNQ and/or BOM
        (no hallucinated IATA code for Mahabaleshwar itself)
Assert: output contains a ground TravelOption whose destination is
        "Mahabaleshwar" (not just "Pune" or "Mumbai") — the path must
        reach the stated destination, not terminate at the gateway city
```

**A6 — No-airport island destination routes via mainland gateway + ferry**
```
Input:  routes=[("Delhi", "Koh Tao")], date_range="2026-07-15"
        (Koh Tao has no airport; access is by ferry from Chumphon or
        Surat Thani, reached by flying to Bangkok BKK/DMK or Surat Thani URT)

Assert: flight_search destination_airports contains at least one of
        BKK, DMK, URT, HKT — no hallucinated IATA code for Koh Tao itself
Assert: output contains a ferry TravelOption with destination "Koh Tao"
        (the path must reach the island, not terminate at the mainland)
```

---

### Test group B: Route completeness

**B1 — Output contains transfers at both city endpoints**
```
Input:  routes=[("Mumbai", "Tokyo")], date_range="2026-07-15"

Assert: output contains at least one TravelOption with mode="flight/one-way"
Assert: output contains a ground TravelOption whose origin or destination
        contains "Mumbai" — the departure-end transfer
Assert: output contains a ground TravelOption whose origin or destination
        contains "Tokyo" — the arrival-end transfer

Why the stricter check: reversible ground transfers means the LLM might
place both transfers at one end only (e.g. two Tokyo ↔ NRT entries),
satisfying a naive "to airport / from airport" check while leaving the
Mumbai end entirely missing.
```

**B2 — Flight TravelOption uses airport-formatted origin/destination**
```
Input:  routes=[("Mumbai", "Tokyo")]

Assert: for each TravelOption with mode="flight/one-way" or "flight/return":
        - origin matches pattern "<IATA> Airport, <City>" or "<City> Airport"
        - destination matches the same pattern
        - origin does not equal "Mumbai" or "Tokyo" (bare city names not acceptable)
```

**B3 — Round-trip: correct flight modes and no duplicate ground transfers**
```
Input:  routes=[("Mumbai", "Tokyo")], trip_type="round_trip",
        date_range="2026-07-15 to 2026-07-25"

Assert: flight_search was called with trip_type="round_trip"
Assert: output contains no TravelOption with mode="flight/one-way"
Assert: output contains at least two TravelOptions with mode="flight/return"
        (one for the outbound leg, one for the return leg)
Assert: output contains exactly one departure-end ground transfer
        (Mumbai ↔ airport) and one arrival-end ground transfer (airport ↔ Tokyo)
        — ground transfers must not appear twice (once per direction)
```

---

## Section 2 — LLM-as-judge Tests

One judge prompt across all scenarios. The judge evaluates the full quality of the returned travel options — completeness, realism, accuracy, and format correctness.

---

**Judge prompt**
```
"A transportation research agent was asked to find travel options for:
   Route(s): {routes}
   Date(s): {date_range}
   User context: '{user_context}'  (empty if none)

   It returned these travel options:
   {travel_options}

   Evaluate the quality across all of the following:

   1. Route completeness — is the full journey covered? For a one-way route:
      departure city → departure airport (transfer) → flight → arrival airport →
      arrival city (transfer). For a round-trip, additionally a return flight leg;
      ground transfers at each city endpoint are shared across directions and
      should appear once, not duplicated per leg. Flag any missing segment or
      any unnecessary duplication of ground transfers.

   2. Transfer realism — do the ground transfer options reflect how travellers
      actually get to/from the airports in these cities? Are multiple modes
      offered where realistic (e.g. metro + taxi for Tokyo, not just taxi)?
      Are the modes plausible for these specific cities?

   3. Airport accuracy — are the correct airports used for each city?
      Flag if a secondary or unlikely airport was used when a primary one
      was available (e.g. using Stansted for a London–Paris route instead
      of Heathrow or Gatwick).

   4. Format correctness — do flight leg origin/destination values use the
      '<IATA> Airport, <City>' format? Are mode values correct
      ('flight/one-way', 'flight/return', 'taxi', 'metro', etc.)?

   Verdict: PASS or FAIL.
   Critique: if PASS, note what was done well and any dimension that was
   only barely adequate. If FAIL, identify each issue specifically —
   which segment is missing, which airport is wrong, which format is off."
```

---

**Scenarios**

| # | Route(s) | Date | Trip type | User context | Primary stress |
|---|---|---|---|---|---|
| S1 | Mumbai → Tokyo | 2026-07-15 | one-way | — | Full path coverage, IATA accuracy |
| S2 | Delhi → Bangkok | 2026-07-15 | one-way | — | Transfer realism (BKK has two airports: BKK/DMK) |
| S3 | Mumbai ↔ Tokyo | 2026-07-15 / 2026-07-25 | round-trip | — | Return leg mode, full round-trip coverage |
| S5 | London → Amsterdam | 2026-06-10 | one-way | — | Multi-airport city (LHR/LGW/STN), short-haul options |
| S6 | Delhi → Mahabaleshwar | 2026-07-15 | one-way | — | No-airport destination, gateway city + extended transfer |
| S7 | Delhi → Koh Tao | 2026-07-15 | one-way | — | No-airport island, gateway city + ferry leg |

---

## Test Data Notes

- **A4 / S5** require knowing that London has LHR, LGW, STN and Paris has CDG, ORY. Bangkok has BKK (Suvarnabhumi) and DMK (Don Mueang). These are stable facts usable as judge ground truth.
- **S5 (London → Amsterdam)** is also interesting because train (Eurostar to Brussels, then onward) is a realistic alternative to flying — the judge can assess whether the specialist considered non-flight options for short-haul routes where they exist.
- **S6 (Mahabaleshwar)**: nearest airports are Pune PNQ (~120km, ~2.5h drive) and Mumbai BOM (~250km, ~5h). Both are valid gateways. The judge should check the extended ground transfer reaches Mahabaleshwar, not just the gateway city.
- **S7 (Koh Tao)**: no airport. Access is by ferry from Chumphon (~2h) or Surat Thani (~6h). Practical flight gateways are Bangkok BKK/DMK and Surat Thani URT. Phuket HKT may also appear as a gateway (large international hub) though it is less direct. All four are valid for the assertion. The judge should check the full path reaches the island and that the ferry leg is present.
- For judge scenarios, present travel options as a list: `mode | operator | origin → destination | duration | cost`.

---

## Coverage Summary

| Test | Failure mode guarded | Requires real API |
|---|---|---|
| A1 | F7 — multi-airport city under-searched | yes |
| A2 | F2 — IATA re-resolved from prior session | yes |
| A3 | F1 — city names in flight_search args | yes |
| A4 | F7 inverse — single-airport city over-specified | yes |
| B1 | F3, F12 — missing transfer segment, both transfers at same endpoint | yes |
| B2 | F4 — bare city name in flight TravelOption | yes |
| B3 | F5, F9 — wrong mode on return leg, duplicated ground transfers | yes |
| S1 | F3, F4, F8 — completeness, format, transfer quality | yes |
| S2 | F7, F8 — airport selection, transfer realism | yes |
| S3 | F5 — round-trip coverage and mode correctness | yes |
| S5 | F7, F8 — multi-airport London, short-haul alternatives | yes |
| A5 | F10, F11 — hallucinated IATA, missing onward transfer | yes |
| A6 | F10, F11 — hallucinated IATA, missing ferry leg | yes |
| S6 | F10, F11 — gateway city routing quality, transfer realism | yes |
| S7 | F10, F11 — access route completeness, alternative routes | yes |
