🧠 1. Vague / Exploratory Intent (Hardest category)

These test interpretation + clarification loops.

“Where should I go for a 5-day trip in June?”
“I want a Europe vibe but not Europe prices.”
“Somewhere chill but not boring.”
“Plan a trip where I can disconnect but still have good food.”
“I want a main character trip.”
“Places that feel like Eat Pray Love but not too expensive.”
“Somewhere not too touristy but still safe.”
“I just want to get out of Bangalore for a bit. Suggestions?”

👉 Forces:

Preference inference
Follow-up questions
Recommendation generation under ambiguity
💸 2. Budget-Constrained Planning

Tests constraint satisfaction + tradeoffs.

“Plan a 7-day international trip under ₹80,000 all inclusive.”
“What are the cheapest countries I can visit from India right now?”
“Trip under $1000 including flights from Bangalore.”
“Where can I go where my money stretches the most?”
“Luxury feel on a budget—where should I go?”
“Is Bali still cheap in 2026?”

👉 Forces:

Flight + accommodation + cost modeling
Currency awareness
Dynamic pricing awareness
✈️ 3. Flight + Logistics Queries

Tests integration with real APIs + time reasoning.

“Cheapest flights from BLR to anywhere next weekend.”
“I want to leave Friday night and be back Monday morning—options?”
“Multi-city: Bangalore → Tokyo → Seoul → Bangalore.”
“Find flights with long layovers so I can explore another city.”
“What’s the least tiring route to New York?”
“Avoid red-eye flights.”

👉 Forces:

Multi-hop planning
Time zone handling
Optimization (price vs comfort)
🏨 4. Stay & Location Preferences

Tests filtering + spatial reasoning.

“Stay near the beach but not crowded.”
“Hotel with a bathtub and a good view.”
“Best areas to stay in Paris for first-time visitors.”
“Safe neighborhoods for solo female travelers.”
“Stay close to nightlife but quiet at night.”

👉 Forces:

Place clustering
Safety heuristics
Tradeoff explanation
🌦️ 5. Weather-Aware Planning

Tests temporal + environmental reasoning.

“Where can I go in July with good weather?”
“Avoid rainy destinations next month.”
“Best winter sun destinations from India.”
“Where is it not too hot right now?”
“Is Thailand worth visiting in June?”

👉 Forces:

Weather API integration
Seasonality knowledge
Risk explanation
🧭 6. Activity-Based Travel

Tests mapping activities → destinations.

“Where can I learn to surf?”
“Best places for scuba diving beginners.”
“I want to see the northern lights.”
“Where can I do a yoga retreat?”
“Places for hiking with great views but easy trails.”
“Where can I work from mountains with good WiFi?”

👉 Forces:

Activity → geography mapping
Skill-level filtering
🍝 7. Culture / Experience-Driven Queries

Very subjective, high-value.

“Where can I enjoy authentic Italian lifestyle and cuisine?”
“Places that feel like old Europe.”
“Where can I experience Japanese culture deeply?”
“I want street food + nightlife.”
“Slow living destinations.”

👉 Forces:

Cultural abstraction
Ranking subjective experiences
🧑‍🤝‍🧑 8. Group-Specific Planning

Conflicting constraints.

“Trip with parents—comfortable, not too hectic.”
“Bachelor trip under ₹50k.”
“Couple trip, romantic but not cliché.”
“Travel with friends—mix of party + chill.”
“Kid-friendly international trips.”

👉 Forces:

Persona modeling
Conflict resolution
⏱️ 9. Time-Constrained Queries

Tests itinerary compression.

“3-day trip from Bangalore.”
“Weekend getaway within driving distance.”
“I only have 36 hours in Singapore—plan it.”
“Layover of 8 hours in Dubai—what can I do?”

👉 Forces:

Time optimization
Route planning
🗺️ 10. Itinerary Generation (Core Feature)

Multi-step reasoning.

“Plan a 5-day Bali itinerary.”
“Give me a day-by-day plan for Japan.”
“Mix of sightseeing + food + relaxation.”
“Not too packed, I want flexibility.”
“Include hidden gems.”

👉 Forces:

Structured output
Balancing density vs leisure
🧾 11. Visa / Documentation / Rules

High-stakes accuracy.

“Do I need a visa for Vietnam?”
“Visa-free countries for Indians?”
“Transit visa needed for layover in Germany?”
“What documents do I need for Schengen?”

👉 Forces:

Up-to-date info
Legal accuracy
🚨 12. Edge / Stress-Test Queries (Important)

These break naive systems.

“Plan me a trip but I don’t know where I want to go.”
“Anywhere but beaches.”
“Surprise me.”
“I want cold weather but also beaches.”
“No flights longer than 5 hours but I want Europe.”
“Plan everything end-to-end.”
“Replan this trip because my flight got cancelled.”
“Optimize this itinerary I made.”
“Is this plan realistic?” (user provides messy plan)

👉 Forces:

Clarification loops
Constraint conflict handling
Plan validation
🔄 13. Real-Time / Adaptive Queries

Requires reactivity.

“Rain forecast changed—what should I do instead?”
“My budget increased, upgrade my trip.”
“Find alternatives because this hotel is sold out.”
“Flight delayed—adjust itinerary.”

👉 Forces:

Stateful agent behavior
Replanning
🧠 14. Preference Learning / Memory

Long-term personalization.

“Trips similar to my last Goa trip.”
“Avoid places like Dubai.”
“I prefer boutique hotels.”
“I hate crowded places.”

👉 Forces:

User profiling
Memory integration
🧪 15. Hybrid / Complex Queries (Real-world messy)

These are the ones that matter most:

“Plan a 6-day trip in September, budget ₹1L, I want good food, not too touristy, maybe international, weather should be nice.”
“Trip with girlfriend, good cafés, aesthetic places, not too expensive, from Bangalore.”
“Somewhere I can work for a week, good WiFi, not too hot, and nice views.”
“2 countries in one trip, budget tight, avoid visa hassle.”
“I want something different, not Thailand, not Bali.”