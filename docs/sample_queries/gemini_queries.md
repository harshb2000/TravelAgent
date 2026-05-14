# Travel Planner AI: User Query & Flow Test Suite

This document outlines a diverse set of real-world queries and multi-step flows to test the robustness of a Travel Planner Agent. Use these to evaluate intent classification, API orchestration, and constraint handling.

---

## 1. High-Level Inspiration & Discovery
*Testing the ability to map "vibes" and abstract desires to concrete locations.*

- **The "Vibe" Match:** "I want a destination that feels like the Amalfi Coast but is less crowded and more affordable for a week in September."
- **Niche Interests:** "Where are the best places in the world to see brutalist architecture while also being near a specialty coffee scene?"
- **Hobby Specific:** "I want to go on a 3-day trekking trip where I can stay in mountain huts rather than tents. Somewhere in South America or Central Asia."
- **Cultural Immersion:** "Where can I experience an authentic 'Salsa' culture that isn't a major tourist trap?"

## 2. Rigid Constraints & Optimization
*Testing the "Math" and "Logic" engines: Balancing budgets, visas, and timing.*

- **Hard Budgeting:** "I have exactly $1,500 for a 10-day trip starting from Buenos Aires. This must include round-trip flights, accommodation, and food. Suggest 3 options."
- **Visa Logic:** "I am an Indian citizen currently in Argentina. Suggest countries in the Balkans I can visit without a pre-arranged visa."
- **Time-Sensitive Weather:** "Find me a destination within a 6-hour flight of London where it is guaranteed to be 20°C+ and sunny during the first week of November."
- **Transit Efficiency:** "I need to visit Berlin, Prague, and Vienna in 7 days. Optimize the route for the least amount of time spent in transit."

## 3. Logistical & "Last-Mile" Planning
*Testing integration with Routes and Places APIs.*

- **The Late Arrival:** "My flight lands at EZE at 11:30 PM. Find me a hotel that has 24-hour check-in and is reachable via a safe, affordable shuttle or car service."
- **Granular Proximity:** "Find a coworking space in Mexico City that is within a 15-minute walk of a highly-rated vegan restaurant and a park."
- **Complex Transport:** "How do I get from the airport in Naples to a specific ferry terminal for Capri using only public transport, and what is the total cost?"

## 4. Real-Time "Agentic" Scenarios
*Testing the agent's ability to handle disruptions and dynamic updates.*

- **The "Re-Route" (Flight Delay):** "My flight to Bangalore via Frankfurt is delayed by 12 hours. Check if I am entitled to EU 261 compensation and find a lounge or day-stay hotel in Frankfurt Airport."
- **The Group Dilemma:** "Planning a trip for 4 people. Two are coming from NYC, two from Paris. We want to meet halfway in a city with a great nightlife scene that costs under $150/night for a 2-bedroom Airbnb."
- **Preference Update (Memory):** "You suggested a trip to Tokyo. Change that—I want to stay in traditional Ryokans instead of modern hotels, but keep the total budget the same."

## 5. "Edge Case" & Stress Tests
*Testing the boundaries of the LLM's reasoning.*

- **The "Impossible" Request:** "Find me a direct flight from London to a remote island in the Pacific for under $200 tomorrow." (Tests how the agent handles failure/refusal).
- **The Hyper-Specific Health/Diet:** "I have a severe nut allergy and I'm vegan. Plan a 3-day food tour in Tokyo where every stop has been verified for these requirements."
- **The Safety Search:** "I'm a solo female traveler. Rank these three neighborhoods in Bogota based on recent safety data and proximity to police stations."
