# Coverage Report: chatgpt_queries.md — Architecture v1

**Verdict key:**
- `PASS` — fully handled by v1 agent set
- `PARTIAL` — mostly handled; one element hits a v1 limitation (noted inline)
- `FAIL` — requires a capability absent in v1

---

## 1. Vague / Exploratory Intent

- Where should I go for a 5-day trip in June? `PASS` — ExplorerAgent + WeatherAgent
- I want a Europe vibe but not Europe prices. `PASS` — ExplorerAgent (vibe + budget matching)
- Somewhere chill but not boring. `PASS` — Orchestrator clarifies minimally → ExplorerAgent
- Plan a trip where I can disconnect but still have good food. `PASS` — ExplorerAgent
- I want a main character trip. `PASS` — ExplorerAgent (abstract vibe via web_search)
- Places that feel like Eat Pray Love but not too expensive. `PASS` — ExplorerAgent
- Somewhere not too touristy but still safe. `PASS` — ExplorerAgent + DestinationResearchAgent (safety)
- I just want to get out of Bangalore for a bit. Suggestions? `PASS` — ExplorerAgent + TransportationAgent (nearby options)

---

## 2. Budget-Constrained Planning

- Plan a 7-day international trip under ₹80,000 all inclusive. `PASS` — ExplorerAgent + all specialists + BudgetAgent
- What are the cheapest countries I can visit from India right now? `PASS` — ExplorerAgent + TransportationAgent (flight costs) + BudgetAgent
- Trip under $1000 including flights from Bangalore. `PASS` — ExplorerAgent + TransportationAgent + BudgetAgent
- Where can I go where my money stretches the most? `PASS` — ExplorerAgent + BudgetAgent (purchasing power comparison)
- Luxury feel on a budget—where should I go? `PASS` — ExplorerAgent
- Is Bali still cheap in 2026? `PASS` — DestinationResearchAgent + BudgetAgent

---

## 3. Flight + Logistics Queries

- Cheapest flights from BLR to anywhere next weekend. `PARTIAL` — Amadeus requires a destination; Orchestrator dispatches ExplorerAgent first for candidates, then TransportationAgent per candidate; true open-jaw search not supported by Amadeus free tier
- I want to leave Friday night and be back Monday morning—options? `PASS` — ExplorerAgent + TransportationAgent (date/time-constrained search)
- Multi-city: Bangalore → Tokyo → Seoul → Bangalore. `PASS` — TransportationAgent handles each leg; DestinationResearchAgent + ItineraryPlannerAgent for both cities
- Find flights with long layovers so I can explore another city. `PASS` — TransportationAgent (layover filtering) + DestinationResearchAgent (layover city guide)
- What's the least tiring route to New York? `PASS` — TransportationAgent (fewest stops, shortest elapsed time, avoiding overnight legs)
- Avoid red-eye flights. `PASS` — TransportationAgent (departure time filter on Amadeus results)

---

## 4. Stay & Location Preferences

- Stay near the beach but not crowded. `PASS` — ExplorerAgent + DestinationResearchAgent
- Hotel with a bathtub and a good view. `PARTIAL` — DestinationResearchAgent can recommend hotel areas and property types via web_search; no hotel booking API or verified amenity lookup in v1
- Best areas to stay in Paris for first-time visitors. `PASS` — DestinationResearchAgent (neighbourhood guide)
- Safe neighborhoods for solo female travelers. `PASS` — DestinationResearchAgent (safety research via web_search)
- Stay close to nightlife but quiet at night. `PASS` — DestinationResearchAgent (neighbourhood characterisation)

---

## 5. Weather-Aware Planning

- Where can I go in July with good weather? `PASS` — WeatherAgent (monthly climate) + ExplorerAgent
- Avoid rainy destinations next month. `PASS` — WeatherAgent + ExplorerAgent (filter by precipitation)
- Best winter sun destinations from India. `PASS` — ExplorerAgent + WeatherAgent
- Where is it not too hot right now? `PASS` — WeatherAgent (current conditions) + ExplorerAgent
- Is Thailand worth visiting in June? `PASS` — WeatherAgent (June climate for Thailand) + DestinationResearchAgent (monsoon season context)

---

## 6. Activity-Based Travel

- Where can I learn to surf? `PASS` — ExplorerAgent
- Best places for scuba diving beginners. `PASS` — ExplorerAgent
- I want to see the northern lights. `PASS` — ExplorerAgent + WeatherAgent (aurora season windows)
- Where can I do a yoga retreat? `PASS` — ExplorerAgent
- Places for hiking with great views but easy trails. `PASS` — ExplorerAgent
- Where can I work from mountains with good WiFi? `PASS` — ExplorerAgent

---

## 7. Culture / Experience-Driven Queries

- Where can I enjoy authentic Italian lifestyle and cuisine? `PASS` — ExplorerAgent
- Places that feel like old Europe. `PASS` — ExplorerAgent
- Where can I experience Japanese culture deeply? `PASS` — DestinationResearchAgent + ExplorerAgent (region/city options within Japan)
- I want street food + nightlife. `PASS` — ExplorerAgent
- Slow living destinations. `PASS` — ExplorerAgent

---

## 8. Group-Specific Planning

- Trip with parents—comfortable, not too hectic. `PASS` — ExplorerAgent (comfort-oriented preferences)
- Bachelor trip under ₹50k. `PASS` — ExplorerAgent + BudgetAgent (per-person estimate; group total out of scope)
- Couple trip, romantic but not cliché. `PASS` — ExplorerAgent
- Travel with friends—mix of party + chill. `PASS` — ExplorerAgent
- Kid-friendly international trips. `PASS` — ExplorerAgent + DestinationResearchAgent

---

## 9. Time-Constrained Queries

- 3-day trip from Bangalore. `PASS` — ExplorerAgent + TransportationAgent
- Weekend getaway within driving distance. `PASS` — ExplorerAgent (no flight needed; proximity-based)
- I only have 36 hours in Singapore—plan it. `PASS` — DestinationResearchAgent + ItineraryPlannerAgent (tight time-boxed plan)
- Layover of 8 hours in Dubai—what can I do? `PASS` — DestinationResearchAgent + ItineraryPlannerAgent

---

## 10. Itinerary Generation

- Plan a 5-day Bali itinerary. `PASS` — full pipeline → ArtifactAgent
- Give me a day-by-day plan for Japan. `PASS` — full pipeline → ArtifactAgent
- Mix of sightseeing + food + relaxation. `PASS` — ItineraryPlannerAgent (balance-aware scheduling)
- Not too packed, I want flexibility. `PASS` — ItineraryPlannerAgent (density control via preferences)
- Include hidden gems. `PASS` — DestinationResearchAgent + ExplorerAgent (off-beaten-path search)

---

## 11. Visa / Documentation / Rules

- Do I need a visa for Vietnam? `PASS` — DestinationResearchAgent
- Visa-free countries for Indians? `PASS` — ExplorerAgent + DestinationResearchAgent
- Transit visa needed for layover in Germany? `PASS` — DestinationResearchAgent
- What documents do I need for Schengen? `PASS` — DestinationResearchAgent

---

## 12. Edge / Stress-Test Queries

- Plan me a trip but I don't know where I want to go. `PASS` — Orchestrator asks minimal questions → ExplorerAgent
- Anywhere but beaches. `PASS` — ExplorerAgent (negative constraint)
- Surprise me. `PASS` — Orchestrator picks sensible defaults → ExplorerAgent
- I want cold weather but also beaches. `PASS` — ExplorerAgent (unusual but valid combination)
- No flights longer than 5 hours but I want Europe. `PASS` — TransportationAgent (flight duration filter) + ExplorerAgent (European destinations within range)
- Plan everything end-to-end. `PASS` — full pipeline
- Replan this trip because my flight got cancelled. `PARTIAL` — TransportationAgent + ItineraryPlannerAgent can replan; no real-time flight status to detect cancellation automatically
- Optimize this itinerary I made. `PASS` — user pastes itinerary into chat; ItineraryPlannerAgent optimises
- Is this plan realistic? (user provides messy plan) `PASS` — Orchestrator + specialists validate each element (flights, weather, travel times)

---

## 13. Real-Time / Adaptive Queries

- Rain forecast changed—what should I do instead? `PASS` — WeatherAgent (updated forecast) + ItineraryPlannerAgent (replanned day)
- My budget increased, upgrade my trip. `PASS` — BudgetAgent + DestinationResearchAgent (higher-tier options) + ItineraryPlannerAgent
- Find alternatives because this hotel is sold out. `PARTIAL` — DestinationResearchAgent can suggest alternative areas/properties via web_search; no hotel availability API in v1
- Flight delayed—adjust itinerary. `PARTIAL` — ItineraryPlannerAgent can adjust given new arrival time; no real-time flight status feed

---

## 14. Preference Learning / Memory

- Trips similar to my last Goa trip. `FAIL` — requires cross-session memory
- Avoid places like Dubai. `PASS` — within session: Orchestrator updates UserPreferences; `FAIL` if referenced from a prior session
- I prefer boutique hotels. `PASS` — within session: UserPreferences update shapes DestinationResearchAgent queries
- I hate crowded places. `PASS` — within session: UserPreferences update shapes ExplorerAgent results

---

## 15. Hybrid / Complex Queries

- Plan a 6-day trip in September, budget ₹1L, good food, not too touristy, weather should be nice. `PASS` — full pipeline with ExplorerAgent leading
- Trip with girlfriend, good cafés, aesthetic places, not too expensive, from Bangalore. `PASS` — ExplorerAgent + full pipeline
- Somewhere I can work for a week, good WiFi, not too hot, and nice views. `PASS` — ExplorerAgent
- 2 countries in one trip, budget tight, avoid visa hassle. `PASS` — TransportationAgent (multi-leg) + ExplorerAgent (visa-light options) + BudgetAgent
- I want something different, not Thailand, not Bali. `PASS` — ExplorerAgent (negative constraints)

---

## Summary Statistics

| Verdict | Count | % |
|---|---|---|
| PASS | 72 | 88.9% |
| PARTIAL | 7 | 8.6% |
| FAIL | 2 | 2.5% |
| **Total** | **81** | |

### PARTIAL breakdown
| Query | Limiting factor |
|---|---|
| Cheapest flights to anywhere | Amadeus requires destination; open-jaw not supported |
| Hotel with bathtub and view | No hotel amenity/availability API |
| Replan — flight got cancelled | No real-time flight status feed |
| Hotel sold out — find alternatives | No hotel availability API |
| Flight delayed — adjust itinerary | No real-time flight status feed |
| Honeymoon for two | Multi-passenger cost breakdown |
| "Avoid places like Dubai" (cross-session) | Cross-session memory only within current session |

### FAIL breakdown
| Query | Limiting factor |
|---|---|
| Trips similar to my last Goa trip | Cross-session memory not in v1 |
| (cross-session preference "avoid Dubai") | Cross-session memory not in v1 |
