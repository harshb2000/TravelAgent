# Evaluation Plan — ItineraryPlannerSpecialist

## What the LLM Does Here

Given a query (trip intent + duration + dates), UserContext, DestinationResearch (full-depth), and WeatherOutput, the specialist must:

1. **Issue parallel web_search calls** — one per destination block or day-range in a single iteration — to enrich Activity objects with `duration_min`, `indoor`, and `source_url`. Activity names in `activity_updates` must match DestinationResearch activity names exactly.
2. **Apply day-type rules** — day 1 is the arrival day (light, orientation only); the final day is the departure day (morning slot only); transit days describe the journey leg, not sightseeing.
3. **Apply weather-aware scheduling** — days flagged as high-precip (`precipitation_prob > 60%` for forecast, `precipitation_sum > 10mm/day` for climate) must receive indoor-heavy primary slots with outdoor `is_alternative=True` slots immediately after.
4. **Respect alternative slot constraints** — at most 2 alternatives per primary slot; at most 3 alternative slots per day; never start a day with an alternative slot.
5. **Incorporate festivals** — events from DestinationResearch.festivals should appear in slot notes or be scheduled directly when they fall within the travel window.
6. **Generate the full `Itinerary`** — one `ItineraryDay` per trip day, in order, with `TimeSlot` entries for each activity.

The wrapper handles pre-validation (full-depth research present), KnowledgeState writes, and empty-itinerary retry. Those are already unit tested.

---

## Failure Modes

| # | Failure | Prompt signal that should prevent it |
|---|---|---|
| F1 | Rainy day has outdoor-heavy primary slots with no indoor alternatives | Prompt instructs high-precip days get indoor primaries + outdoor alternatives |
| F2 | Alternative slot appears at start of a day (before any primary) | Prompt: never start a day with an alternative slot |
| F3 | More than 2 alternative slots follow a single primary | Prompt: at most 2 alternatives per primary |
| F4 | More than 3 alternative slots in a single day | Prompt: at most 3 alternative slots per day total |
| F5 | Arrival day is over-packed with full sightseeing schedule | Prompt: day 1 is arrival — light, orientation activities only |
| F6 | Departure day has afternoon or evening activity slots | Prompt: departure day morning only; afternoon/evening left clear for travel |
| F7 | Transit day has sightseeing slots instead of describing the journey | Prompt: transit days describe the journey leg with realistic travel time |
| F8a | DestinationResearch activity used in the itinerary is renamed in activity_updates — enrichment becomes orphaned | Prompt: use activity names that match DestinationResearch activities exactly |
| F8b | Activity added to the itinerary that is not in DestinationResearch has no activity_updates entry — new activity is never enriched | Any activity placed in a slot, whether from DestinationResearch or newly introduced, must appear in activity_updates |
| F9 | Activity enrichment searches are serialised rather than parallel | Prompt: issue parallel web_search calls in a single iteration |
| F10 | Activities placed in itinerary slots lack enrichment (duration_min, indoor, source_url absent) | Prompt: enrich activities via web_search — enrichment covers the activities used in the itinerary, not all of DestinationResearch |
| F11 | Multi-city trip missing transit day between destinations | Prompt: transit days are required for inter-city travel |
| F12 | Festival in DestinationResearch not reflected anywhere in the itinerary | Prompt: incorporate festivals and closures in notes; prioritise special events |
| F13 | Activity selection ignores user preferences — itinerary is generic regardless of stated interests, travel style, or group composition | Prompt instructs activity selection to reflect UserContext; covered by judge criterion 2 |
| F14 | High-precip day has no weather_note | Prompt implies weather caveats should be visible to the traveller |

---

## Section 1 — Assertion-based Tests

### Test group A: Day structure rules

**A1 — Arrival day is light**
```
Input:  query="5 nights Tokyo, arrival June 20", with known start_date

Assert: days[0].is_arrival == True
Assert: len(days[0].slots) <= 2
        (arrival day should have at most 2 orientation activities — not a packed
        sightseeing schedule)
```

**A2 — Departure day is morning-only**
```
Input:  query="5 nights Tokyo, departure June 25"

Assert: last day has is_departure == True
Assert: no slot on the departure day has a start_time that is "night",
        "evening", or a time string >= "15:00"
        (afternoon/evening must be left clear for travel)
```

**A3 — Transit day describes the journey, not sightseeing**
```
Precondition: multi-city trip — "5 days Tokyo + 5 days Kyoto, transit on day 6"

Assert: the transit day has is_transit == True
Assert: at least one slot's activity.name contains a travel-related term
        ("flight", "train", "shinkansen", "transfer", "travel", "depart", "arrive",
        "journey" — case-insensitive)
```

---

### Test group B: Weather-aware scheduling

**B1 — High-precip forecast day uses indoor primaries**
```
Precondition: WeatherOutput (forecast mode) includes a day with precipitation_prob=80%

Assert: for that specific day, at least one non-alternative (primary) slot has
        activity.indoor == True

Why this matters: a clear afternoon at Ueno Park on a day forecast to rain is
a failure of weather-aware scheduling.
```

**B2 — Alternative slot never starts a day**
```
For any day with at least one slot:

Assert: slots[0].is_alternative == False

Why this matters: an alternative has no primary to be contingent on if it leads
the day — it becomes effectively a primary without the LLM making that explicit.
```

**B3 — At most 2 alternatives per primary slot**
```
For any day, scan the slot list for runs of consecutive is_alternative=True slots:

Assert: no such run exceeds length 2

Example: [primary, alt, alt, alt] → FAIL (run of 3 after a single primary)
         [primary, alt, alt, primary, alt] → PASS
```

**B4 — At most 3 alternative slots per day total**
```
For any day:

Assert: count(slot.is_alternative == True for slot in day.slots) <= 3
```

---

### Test group C: Activity enrichment

**C1 — At least one web_search issued for enrichment**
```
For any valid run where the itinerary slots contain named activities:

Assert: ConversationHistory contains at least one web_search call

Why this matters: activities placed in the itinerary should be enriched from
web results, not populated with duration_min/indoor from training knowledge alone.
```

**C2 — Parallel searches for a multi-destination trip**
```
Input:  query covers 2+ destinations (e.g. "5 days Tokyo + 5 days Kyoto")

Assert: at least one LLM response contains multiple web_search calls
        in the same message (parallel tool calls, one per destination)

Why this matters: the prompt instructs one search per destination block in a
single iteration. Serialising them wastes iterations.
```

**C3 — every itinerary activity has a matching activity_updates entry**
```
Collect all activity names from the itinerary slots (excluding transit-leg
descriptions on transit days).

Assert: for each activity name, a matching entry exists in activity_updates
        for its destination — using the exact name as it appears in the slot
Assert: those entries have at least duration_min or source_url populated
        (enrichment actually occurred, not just the name echoed back)

This covers two sub-cases:
  - Known activity (from DestinationResearch): the name in the slot and in
    activity_updates must match exactly — a paraphrase or abbreviation
    (e.g. "Senso-ji" for "Senso-ji Temple") is a FAIL because the wrapper
    merges enrichment by name and a mismatch orphans the data.
  - New activity (not in DestinationResearch): an activity_updates entry must
    still exist — the planner introduced it, so it is responsible for
    enriching it.
```

---

## Section 2 — LLM-as-judge Tests

One judge prompt used across all scenarios. Each scenario stresses a different criterion but the judge evaluates all dimensions holistically.

---

**Judge prompt**
```
"A travel itinerary planner was given this task:
   Query: '{query}'
   User context: '{user_context}'  (empty string if none)
   Destinations: {destinations}
   Weather summary: '{weather_summary}'
     (comma-separated: 'Day N: clear / high-precip')

   Tool call log (web_search queries issued, in order):
   {conversation_history}

   It produced this itinerary:
   {itinerary}

   It also returned these activity enrichments:
   {activity_updates}
     (destination → list of: name | duration_min | indoor | source_url)

   Evaluate the quality across all of the following:

   1. Day quality and variety — does each day offer a coherent, interesting
      programme? Is the day well-paced — not so packed that transit time is
      impossible, not so sparse that it feels underprepared? If the user has
      a focused intent (e.g. a surfing trip, a bar-hopping itinerary), repeated
      activity types are expected and correct — flag repetition only when it
      appears unintentional or generic rather than driven by the query.

   2. Interest and context alignment — if user context mentions interests,
      travel style, or group composition, does the itinerary reflect them?
      A surfer's itinerary should look different from a culture enthusiast's;
      a family with young children needs different pacing than solo backpackers.

   3. Weather awareness — on days marked as high-precip, are the primary
      activities genuinely indoor-friendly given the user's interests? If the
      user has mixed indoor/outdoor interests, are alternatives present so they
      can take advantage of a weather break? Are weather notes present on
      high-precip days so the traveller knows what to expect?

   4. Day-type correctness — is day 1 appropriately light (orientation only)?
      Is the final day morning-only? If transit days exist, do they describe
      the journey rather than other activities?

   5. Festival and event incorporation — if festivals or notable events appear
      in the destination research, are they reflected in the itinerary (scheduled
      during the relevant day, or noted with a booking/crowd caveat)?

   6. Search strategy — were enrichment queries specific and venue-targeted
      (e.g. 'Senso-ji Temple Tokyo opening hours duration' rather than 'Tokyo
      attractions')? Were searches issued in parallel for multi-destination
      trips, or needlessly serialised? Were any queries redundant?

   Verdict: PASS or FAIL.
   A result can fail due to a single severe issue or multiple moderate ones.
   Critique: if PASS, note what was done well and any dimension that was only
   barely adequate. If FAIL, identify each issue specifically — quote slot
   names that clash with interests, name the rainy day that has no indoor
   alternatives, or quote the enrichment query that was too generic."
```

---

**Scenarios**

| # | Query | User context | Weather | Primary stress |
|---|---|---|---|---|
| S1 | "5 nights Tokyo, arrival June 20, mid-pace" | "Interested in food and cultural history" | All clear | Day quality, interest alignment |
| S2 | "7 nights Bali, relaxed pace, arrival July 5" | "Couple, loves surfing and local food" | Days 3 and 5 high-precip | Weather-aware scheduling, interest alignment |
| S3 | "5 nights Kyoto, arrival July 16" | — | All clear | Festival incorporation (Gion Matsuri runs July 1–31) |
| S4 | "7 nights Mumbai, arrival August 10" | "Solo traveller, interested in street food and architecture" | Days 2, 4, 6, 7 high-precip (monsoon season) | Multi-rainy-day scheduling, alternatives quality |
| S5 | "10 nights total: 5 Tokyo + 5 Kyoto, arrival June 20" | "First-time Japan visitor, pace: moderate" | All clear | Multi-destination coherence, transit day, day-type rules |

---

## Test Data Notes

- **Arrival/departure day assertion**: for A2, treat "night" and "evening" as FAIL keywords in start_time; treat any time string ≥ "15:00" as FAIL.
- **S3 (Gion Matsuri)**: the Kyoto research context should include "Gion Matsuri (July 1–31)" in festivals. The judge evaluates whether the itinerary mentions evening processions or crowd warnings, not just that Gion Matsuri appears in a top-level notes field.
- **S4 (Mumbai monsoon)**: weather context should mark days 2, 4, 6, 7 as high-precip (precipitation_sum > 10mm). Judge evaluates whether the programme for those days is realistically adapted vs generic indoor filler.
- **S5 (multi-destination)**: transit day should fall on day 6 (travel Tokyo → Kyoto). Judge checks it is correctly typed as transit and describes the Shinkansen leg, and that each city block has distinct character.
- Present the itinerary to the judge in the rendered format: `Day N (Location) [flags] — weather_note: / HH:MM [alt] | Activity (indoor/outdoor, Xmin) @ Location — notes`.
- Present the tool call log as a numbered list: `1. web_search("query")`. For multi-destination runs, note which destination each query targets.
- Present activity_updates as: `destination → name | duration_min | indoor | source_url (truncated)`.

---

## Coverage Summary

| Test | Failure mode guarded | Requires real API |
|---|---|---|
| A1 | F5 — arrival day over-packed | yes |
| A2 | F6 — departure day afternoon slots | yes |
| A3 | F7 — transit day has sightseeing | yes (multi-city input) |
| B1 | F1 — rainy day outdoor-heavy primaries | no (stubbed weather) |
| B2 | F2 — alternative slot starts day | yes |
| B3 | F3 — more than 2 alternatives per primary | yes |
| B4 | F4 — more than 3 alternatives per day | yes |
| S1, S2 | F13 — preference-blind activity selection (judge criterion 2) | yes |
| C1 | F10 — no enrichment searches at all | yes |
| C2 | F9 — enrichment searches serialised | yes (multi-city) |
| C3 | F8a, F8b, F10 — activity names mismatched or missing from activity_updates | yes |
| S1 | F8, F12 — enrichment quality, interest alignment | yes |
| S2 | F1, F13 — weather scheduling correctness | yes |
| S3 | F12 — festival not incorporated | yes |
| S4 | F1, F3, F4 — multi-day weather scheduling, alternative limits | yes |
| S5 | F7, F11, F13 — transit day, multi-city coherence | yes (multi-city) |
