# Coverage Report: claude_queries.md — Architecture v1

**Verdict key:**
- `PASS` — fully handled by v1 agent set
- `PARTIAL` — mostly handled; one element hits a v1 limitation (noted inline)
- `FAIL` — requires a capability absent in v1

---

## Experience-led

- Where can I learn to surf? `PASS` — ExplorerAgent (activity→destination mapping)
- Where can I enjoy authentic Italian lifestyle and cuisine? `PASS` — ExplorerAgent (vibe/culture discovery)
- I want to see the northern lights `PASS` — ExplorerAgent + WeatherAgent (seasonal window) + DestinationResearchAgent
- I want a trip that feels like a Studio Ghibli movie `PASS` — ExplorerAgent (abstract vibe matching via web_search)
- Where can I go stargazing away from city lights? `PASS` — ExplorerAgent
- I want to eat at a Michelin-starred restaurant but not in Paris `PASS` — ExplorerAgent + DestinationResearchAgent

---

## Budget-constrained

- What are underrated hidden gems I can travel to within $1000? `PASS` — ExplorerAgent + BudgetAgent
- I have 3 days and ₹15,000 — where can I go from Bengaluru? `PASS` — ExplorerAgent + TransportationAgent + BudgetAgent
- Plan a honeymoon in Europe for under $3000 for two people `PARTIAL` — full planning works; multi-passenger cost breakdown is out of scope (per-person estimates only)
- What is the cheapest time of year to fly to Japan? `PASS` — ExplorerAgent (pricing trends via web_search) + WeatherAgent (off-peak windows)
- Travel Southeast Asia for a month, absolute minimum spend `PASS` — ExplorerAgent + BudgetAgent + DestinationResearchAgent

---

## Constraint-heavy

- I'm vegan, travelling with a 5-year-old, and need wheelchair access. Plan 4 days in Rome. `PARTIAL` — DestinationResearchAgent can search for accessible and vegan-friendly options via web_search; cannot verify individual venue accessibility in real time
- I have a severe nut allergy. Where in Asia is safest to travel? `PASS` — ExplorerAgent + DestinationResearchAgent (allergy safety by cuisine culture)
- I can only travel on long weekends this year — suggest 12 trips from Delhi `PASS` — WeatherAgent + ExplorerAgent + TransportationAgent; public holiday calendar for source country included in timing research
- My partner hates beaches but I love them. Plan a compromise trip. `PASS` — ExplorerAgent (conflicting preference resolution)
- Visa-free destinations from Indian passport under $800 `PASS` — ExplorerAgent + DestinationResearchAgent (visa policy) + BudgetAgent
- No flights — only trains and ferries — London to Istanbul `PASS` — TransportationAgent (overland routes via web_search)

---

## Itinerary requests

- Plan 7 days in Japan for first-time visitors `PASS` — DestinationResearchAgent + WeatherAgent + ItineraryPlannerAgent + ArtifactAgent
- Road trip from San Francisco to Portland — what should I see? `PASS` — DestinationResearchAgent (stops along route) + ItineraryPlannerAgent
- I have a 9-hour layover in Dubai — what can I do? `PASS` — DestinationResearchAgent + ItineraryPlannerAgent (condensed time-boxed plan)
- Visit a different country every day for 5 days starting in Amsterdam `PASS` — TransportationAgent (multi-leg) + DestinationResearchAgent per country + ItineraryPlannerAgent
- Redo my itinerary but cut Monday — I need to fly back early `PASS` — ItineraryPlannerAgent replans with updated constraints (within session); `FAIL` if itinerary was from a prior session (no cross-session memory)

---

## Timing & seasonality

- When is the best time to visit Rajasthan? `PASS` — WeatherAgent (monthly climate) + DestinationResearchAgent (festivals, peak/off-peak)
- I want to see cherry blossoms — where and when? `PASS` — ExplorerAgent + WeatherAgent + DestinationResearchAgent (bloom calendar)
- I want to attend the Rio Carnival — plan the full trip `PASS` — DestinationResearchAgent (Carnival dates, events) + TransportationAgent + WeatherAgent + ItineraryPlannerAgent
- Which of my saved destinations is best to visit this December? `FAIL` — requires cross-session memory/persistence; no saved destinations in v1

---

## Ambiguous / conversational

- I want to travel somewhere nice `PASS` — Orchestrator asks clarifying questions → ExplorerAgent
- Book me a trip to Bali next month `PARTIAL` — full planning produced; booking is permanently out of scope
- Something similar to what I did last year `FAIL` — requires cross-session memory
- I just need a break `PASS` — Orchestrator asks minimal clarifying questions (duration? budget? vibe?) → ExplorerAgent
- Is this a good time to visit Morocco? `PASS` — WeatherAgent (current season) + DestinationResearchAgent (events, advisories)

---

## Safety & logistics

- Is it safe to travel to Pakistan right now? `PASS` — DestinationResearchAgent (safety advisories via web_search)
- Do I need any vaccinations for Tanzania? `PASS` — DestinationResearchAgent (health requirements via web_search)
- Entry requirements for Japan on an Indian passport `PASS` — DestinationResearchAgent (visa/entry policy)
- My flight got cancelled mid-trip — what are my options? `PARTIAL` — TransportationAgent can search for alternatives; no real-time flight status or rebooking capability
- What currency should I carry in Vietnam and how much? `PASS` — BudgetAgent (currency conversion) + DestinationResearchAgent (cash norms, ATM availability)

---

## Summary Statistics

| Verdict | Count | % |
|---|---|---|
| PASS | 29 | 80.6% |
| PARTIAL | 5 | 13.9% |
| FAIL | 2 | 5.6% |
| **Total** | **36** | |

### PARTIAL breakdown
| Query | Limiting factor |
|---|---|
| Honeymoon for two people | Multi-passenger cost breakdown |
| Vegan + wheelchair + 5-year-old in Rome | Cannot verify individual venue accessibility in real time |
| Book me a trip to Bali | Booking permanently out of scope |
| Redo itinerary (cross-session) | No cross-session memory |
| Flight got cancelled | No real-time flight status |

### FAIL breakdown
| Query | Limiting factor |
|---|---|
| Which of my saved destinations | Cross-session persistence not in v1 |
| Something similar to what I did last year | Cross-session memory not in v1 |
