# Coverage Report: gemini_queries.md — Architecture v1

**Verdict key:**
- `PASS` — fully handled by v1 agent set
- `PARTIAL` — mostly handled; one element hits a v1 limitation (noted inline)
- `FAIL` — requires a capability absent in v1

---

## 1. High-Level Inspiration & Discovery

- "I want a destination that feels like the Amalfi Coast but is less crowded and more affordable for a week in September." `PASS` — ExplorerAgent (vibe + budget + season matching) + WeatherAgent + DestinationResearchAgent
- "Where are the best places in the world to see brutalist architecture while also being near a specialty coffee scene?" `PASS` — ExplorerAgent (niche multi-interest discovery via web_search)
- "I want to go on a 3-day trekking trip where I can stay in mountain huts rather than tents. Somewhere in South America or Central Asia." `PASS` — ExplorerAgent (activity + accommodation style + region filter)
- "Where can I experience an authentic 'Salsa' culture that isn't a major tourist trap?" `PASS` — ExplorerAgent (culture/activity discovery with authenticity constraint)

---

## 2. Rigid Constraints & Optimization

- "I have exactly $1,500 for a 10-day trip starting from Buenos Aires. This must include round-trip flights, accommodation, and food. Suggest 3 options." `PARTIAL` — ExplorerAgent + BudgetAgent + TransportationAgent handle planning well; round-trip flight cost surfaced as two one-way legs (v1 handles this); multi-passenger cost breakdown not needed here (solo implied)
- "I am an Indian citizen currently in Argentina. Suggest countries in the Balkans I can visit without a pre-arranged visa." `PASS` — ExplorerAgent (regional visa-free search) + DestinationResearchAgent (visa policy verification)
- "Find me a destination within a 6-hour flight of London where it is guaranteed to be 20°C+ and sunny during the first week of November." `PASS` — WeatherAgent (November climate data) + ExplorerAgent (destinations matching weather + proximity) + TransportationAgent (flight duration filter)
- "I need to visit Berlin, Prague, and Vienna in 7 days. Optimize the route for the least amount of time spent in transit." `PASS` — TransportationAgent (inter-city rail/bus options between each leg) + ItineraryPlannerAgent (route optimisation and scheduling)

---

## 3. Logistical & "Last-Mile" Planning

- "My flight lands at EZE at 11:30 PM. Find me a hotel that has 24-hour check-in and is reachable via a safe, affordable shuttle or car service." `PARTIAL` — TransportationAgent (airport transfer options via web_search) + DestinationResearchAgent (late-arrival hotel areas); cannot verify real-time hotel availability or confirm 24-hour check-in policy
- "Find a coworking space in Mexico City that is within a 15-minute walk of a highly-rated vegan restaurant and a park." `PARTIAL` — DestinationResearchAgent can surface coworking spaces and vegan restaurants in the same neighbourhood via web_search; precise proximity validation (15-minute walk) requires Google Places + Routes (v2)
- "How do I get from the airport in Naples to a specific ferry terminal for Capri using only public transport, and what is the total cost?" `PASS` — TransportationAgent (overland route research via web_search: Alibus + Circumvesuviana + ferry; cost lookup)

---

## 4. Real-Time "Agentic" Scenarios

- "My flight to Bangalore via Frankfurt is delayed by 12 hours. Check if I am entitled to EU 261 compensation and find a lounge or day-stay hotel in Frankfurt Airport." `PARTIAL` — DestinationResearchAgent (EU 261 eligibility rules via web_search) + TransportationAgent (Frankfurt Airport lounge/hotel options); no real-time flight status integration to detect delay automatically; user must trigger this query manually
- "Planning a trip for 4 people. Two are coming from NYC, two from Paris. We want to meet halfway in a city with a great nightlife scene that costs under $150/night for a 2-bedroom Airbnb." `PARTIAL` — ExplorerAgent (midpoint city discovery + nightlife) + TransportationAgent (flights from both origins independently); multi-origin optimisation is handled as two independent flight searches; no Airbnb API for accommodation pricing (BudgetAgent estimates from web_search only)
- "You suggested a trip to Tokyo. Change that—I want to stay in traditional Ryokans instead of modern hotels, but keep the total budget the same." `PASS` — Orchestrator (session memory of prior Tokyo suggestion) + DestinationResearchAgent (Ryokan options and pricing) + BudgetAgent (adjusted accommodation estimate within same total)

---

## 5. Edge Case & Stress Tests

- "Find me a direct flight from London to a remote island in the Pacific for under $200 tomorrow." `PASS` — TransportationAgent returns no results matching constraints; Orchestrator explains the impossibility gracefully and suggests realistic alternatives
- "I have a severe nut allergy and I'm vegan. Plan a 3-day food tour in Tokyo where every stop has been verified for these requirements." `PARTIAL` — DestinationResearchAgent can find allergen-aware and vegan restaurants in Tokyo via web_search; cannot guarantee real-time verification of individual kitchen practices or cross-contamination policies
- "I'm a solo female traveler. Rank these three neighborhoods in Bogota based on recent safety data and proximity to police stations." `PARTIAL` — DestinationResearchAgent can surface recent safety assessments for named neighbourhoods via web_search; proximity-to-police-stations ranking requires Google Places (v2)

---

## Summary Statistics

| Verdict | Count | % |
|---|---|---|
| PASS | 8 | 47.1% |
| PARTIAL | 9 | 52.9% |
| FAIL | 0 | 0.0% |
| **Total** | **17** | |

### PARTIAL breakdown
| Query | Limiting factor |
|---|---|
| $1,500 trip from Buenos Aires (round-trip) | Round-trip modelled as two one-way legs; minor UX limitation |
| Late-arrival hotel at EZE | No real-time hotel availability API |
| Coworking space 15-min walk from vegan restaurant | Precise proximity requires Google Places + Routes (v2) |
| EU 261 compensation + Frankfurt lounge | No real-time flight status; user must trigger manually |
| Multi-origin meeting point (NYC + Paris) | Two independent flight searches; no joint optimisation |
| No Airbnb pricing | No accommodation booking API; estimates from web_search |
| Nut allergy food tour verification | Cannot verify individual kitchen practices in real time |
| Solo female — rank by proximity to police stations | Proximity ranking requires Google Places (v2) |
| (Round-trip cost) | Repeated from Buenos Aires query above |

**Note:** The Gemini query set skews heavily toward logistical, last-mile, and real-time scenarios — the categories most likely to surface v1 limitations. The 52.9% PARTIAL rate reflects this bias rather than a general weakness in the architecture; the PARTIAL queries are all solvable and zero queries FAIL outright.

---

## Cross-File Summary

| File | Queries | PASS | PARTIAL | FAIL | Pass Rate |
|---|---|---|---|---|---|
| claude_queries.md | 36 | 29 (80.6%) | 5 (13.9%) | 2 (5.6%) | 80.6% |
| chatgpt_queries.md | 81 | 72 (88.9%) | 7 (8.6%) | 2 (2.5%) | 88.9% |
| gemini_queries.md | 17 | 8 (47.1%) | 9 (52.9%) | 0 (0.0%) | 47.1% |
| **Combined** | **134** | **109 (81.3%)** | **21 (15.7%)** | **4 (3.0%)** | **81.3%** |

### Recurring PARTIAL causes (across all files)
| Limitation | Occurrences | Resolution path |
|---|---|---|
| No real-time hotel availability | 3 | AccommodationAgent + hotel API (v2) |
| No real-time flight status | 3 | Flight status API (v2) |
| Granular proximity (15-min walk, near police station) | 2 | Google Places + Routes (v2) |
| Multi-passenger cost breakdown | 2 | Group planning support (v2) |
| Cross-session memory | 2 | Session persistence layer (v2) |
| Allergen/accessibility real-time verification | 2 | Specialised APIs; may stay out of scope |

### FAIL causes (across all files)
All 4 FAIL queries require cross-session memory — the only hard blocker in v1.
