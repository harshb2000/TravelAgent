# Roadmap

---

## v1 — MVP (current)

**Theme:** Single-leg trip planning via CLI, real data, hand-rolled agentic loop.

- Conversational intent extraction (origin, destination, dates, budget)
- Flight search via Amadeus sandbox
- Weather forecast via Open-Meteo
- Destination research via Tavily web search
- Budget breakdown (flights + accommodation estimate + daily expenses)
- Day-by-day itinerary saved as Markdown
- Provider-agnostic LLM via raw HTTP (Anthropic, Groq, Ollama, etc.)

**Success criteria:** User can go from "I want to go to Tokyo in June" to a saved itinerary in one CLI session.

---

## v2 — Depth & Usability

**Theme:** Richer data, more useful output, better user experience.

### Data & Features
- **Round-trip flight search** — add return leg to Amadeus query; show total round-trip price
- **Currency conversion** — add `exchangerate.host` (free, no key) to convert costs to user's home currency
- **Hotel cost estimates via API** — evaluate Amadeus hotel search or Booking.com API; replace Tavily synthesis with real data
- **Accommodation range by category** — hostel / mid-range hotel / boutique; user picks comfort level
- **Real-time event search** — Tavily queries for festivals, concerts, exhibitions at destination during trip dates
- **Per-day weather-aware itinerary** — if weather changes significantly mid-trip, reflect it in the schedule

### UX & Output
- **PDF itinerary export** — `reportlab` or `weasyprint`; formatted trip summary document
- **`--resume` flag** — reload a previous session from a saved JSON conversation file
- **Itinerary regeneration** — user can say "re-do the itinerary with more outdoor activities" without re-running all tools
- **Web frontend (Gradio)** — simple Gradio chat UI wrapping the same agent loop; no backend changes needed

### Engineering
- **Async tool execution** — run independent tool calls (weather + web search + flights) concurrently with `asyncio`; reduces total wait time
- **Session persistence** — save/load `ConversationSession` to JSON file for `--resume`
- **Structured logging** — replace `--debug` print statements with `structlog`

---

## v3 — Platform & Integration

**Theme:** Move beyond trip planning into trip management and booking adjacent features.

### Features
- **Multi-city routing** — support A→B→C itineraries; multiple Amadeus flight queries; combined budget
- **Group travel** — `adults=N` parameter; per-person cost breakdown
- **Packing list generation** — based on weather forecast and activity types
- **Restaurant recommendations** — Yelp Fusion API or Foursquare Places API; add lunch/dinner suggestions to itinerary
- **Local transportation** — estimate inter-city rail/bus costs; add to budget
- **Visa application links** — direct links to official visa application portals

### Infrastructure
- **FastAPI backend** — expose the agent loop as a REST API; decouple CLI and frontend
- **React/Next.js frontend** — proper chat UI with streaming responses
- **User accounts** — saved trips, trip history, preference profiles (SQLite → PostgreSQL)
- **Notifications** — email itinerary delivery via SendGrid; flight price drop alerts

---

## Tech Debt / Cleanup (ongoing)

These aren't features but should be tracked:

- [ ] Amadeus sandbox → production key (requires business verification; document the upgrade path)
- [ ] Add explicit token counting to avoid hitting context window limits on long sessions
- [ ] Rate-limit tracking across sessions (not just per-session) once Tavily call count matters at scale
- [ ] Pin exact dependency versions in `requirements.txt` once the initial implementation stabilizes
