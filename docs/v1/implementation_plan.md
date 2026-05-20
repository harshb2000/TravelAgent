# Implementation Plan v1

Build order follows dependency order. Each non-trivial phase follows the same cycle:
**scaffold** (passthrough stubs) → **tests** (write against ideal behaviour) → **verify red** (all fail) → **implement** (real logic) → **verify green** (all pass, refine if needed).

Read `architecture.md` and `philosophy.md` first — the design decisions there drive the structure here.

---

## Directory Layout

```
src/
├── main.py
├── requirements.txt
├── .env.example
├── config/
│   └── settings.py
├── clients/
│   ├── llm_client.py
│   ├── search_client.py
│   ├── amadeus_client.py
│   ├── weather_client.py
│   └── currency_client.py
├── tools/
│   ├── base.py
│   ├── web_search.py
│   ├── flight_search.py
│   ├── weather_forecast.py
│   ├── climate_summary.py
│   ├── currency_convert.py
│   ├── calculate.py
│   └── file_write.py
├── agent/
│   ├── harness.py          # SimpleReActAgent (domain-agnostic)
│   ├── session.py          # ConversationHistory
│   ├── orchestrator.py     # TravelAgent orchestrator
│   └── prompts/
│       ├── orchestrator.py
│       ├── explorer.py
│       ├── destination_research.py
│       ├── transportation.py
│       ├── weather.py
│       ├── budget.py
│       ├── itinerary_planner.py
│       └── artifact.py
├── specialists/
│   ├── explorer.py
│   ├── destination_research.py
│   ├── transportation.py
│   ├── weather.py
│   ├── budget.py
│   ├── itinerary_planner.py
│   └── artifact.py
└── tests/
    ├── test_llm_client.py
    ├── test_harness.py
    ├── test_tools.py
    ├── test_specialists.py
    ├── test_orchestrator.py
    └── fixtures/
        ├── openmeteo_forecast_tokyo.json
        ├── openmeteo_climate_tokyo_june.json
        ├── frankfurter_usd_rates.json
        ├── tavily_destination_tokyo.json
        ├── tavily_visa_japan.json
        ├── tavily_timing_tokyo.json
        └── serpapi_flights_bom_nrt.json
```

---

## Phase 1: Project Scaffolding

**Goal:** Runnable skeleton, all imports resolve, no business logic.

- [x] Create all directories with `__init__.py`: `src/`, `src/agent/`, `src/agent/prompts/`, `src/clients/`, `src/tools/`, `src/specialists/`, `src/config/`, `src/tests/`, `src/tests/fixtures/`
- [x] Write `src/requirements.txt`: `httpx`, `pydantic`, `pydantic-settings`, `python-dotenv`, `tavily-python`, `rich`, `pytest`, `pytest-mock`, `nltk` (for candidate scoring: stop words, lemmatisation)
- [x] Write `src/.env.example`:
  ```
  LLM_BASE_URL=https://api.anthropic.com/v1
  LLM_API_KEY=sk-ant-...
  LLM_MODEL=claude-sonnet-4-6
  LLM_EXTRA_HEADERS={"anthropic-version": "2023-06-01"}
  AMADEUS_CLIENT_ID=...
  AMADEUS_CLIENT_SECRET=...
  AMADEUS_ENV=test
  TAVILY_API_KEY=tvly-...
  ```
- [x] Write `src/config/settings.py` — Pydantic `BaseSettings` reading from `.env`; typed fields for all keys; `llm_extra_headers: dict` parsed from JSON string (default `{}`)
- [x] Write `src/main.py` — `input()` loop that echoes input (stub)
- [x] Verify: `python src/main.py` runs, all imports resolve

---

## Phase 2: LLM Client + Session

**Goal:** Multi-turn LLM conversation via raw HTTP. No tools yet.

Messages are raw `dict` in OpenAI format — no Pydantic models in this phase.

**Scaffold:**
- [x] `clients/llm_client.py` — `LLMClient` class with `chat()` returning a hardcoded `{"role": "assistant", "content": "stub", "finish_reason": "stop"}` dict; `LLMError` defined but never raised
- [x] `agent/session.py` — `ConversationHistory` class with all methods as no-ops and `messages` returning `[]`

**Tests (`tests/test_llm_client.py`):**
- [x] `LLMClient.chat()` with mocked `httpx.post` returns `choices[0].message`
- [x] Headers from `llm_extra_headers` are passed through to the request
- [x] `LLMError` raised on non-200 response
- [x] `ConversationHistory` methods produce correct message dicts in the right order

**Verify red:** `pytest tests/test_llm_client.py` — all tests fail

**Implement:**
- [x] `clients/llm_client.py`
  - `LLMClient(base_url, api_key, model, extra_headers: dict = {})`
  - `chat(messages: list[dict], tools: list[dict] | None = None) -> dict`
  - `httpx.post` to `{base_url}/chat/completions` with `Authorization: Bearer {api_key}` + any `extra_headers`
  - Returns `response.json()["choices"][0]["message"]`
  - Raises `LLMError` on non-200
- [x] `agent/session.py`
  - `ConversationHistory(system_prompt: str)`
  - Stores `list[dict]` starting with `{"role": "system", "content": system_prompt}`
  - `add_user(content: str)`
  - `add_assistant(msg: dict)` — appends raw message dict (may include `tool_calls`)
  - `add_tool_result(tool_call_id: str, content: str)`
  - `messages` property returns the full list
- [x] Wire `src/main.py` for basic multi-turn chat to verify end-to-end

**Verify green:** `pytest tests/test_llm_client.py` — all tests pass

---

## Phase 3: Agentic Harness

**Goal:** General-purpose, domain-agnostic agentic infrastructure. `SimpleReActAgent` is the only agent type — used by the orchestrator and all specialists. Agents hold their own `ConversationHistory` and are instantiated once per session; `run(task)` always appends to and continues the internal history. Parallel tool calls are dispatched concurrently via `ThreadPoolExecutor`. Agents are told their iteration budget upfront and self-regulate.

**Scaffold:**
- [x] `tools/base.py` — `BaseTool` ABC with abstract `execute()`; `to_llm_definition()` returning an empty dict stub
- [x] `agent/harness.py` — `SimpleReActAgent.__init__()` accepts args but ignores tools; `run()` returns `"stub"` immediately without calling the LLM

**Tests (`tests/test_harness.py`):**
- [x] `SimpleReActAgent.run(task)` returns content when first LLM response has `finish_reason == "stop"`
- [x] Single tool call routed to correct `BaseTool.execute()` and result appended to internal history before re-calling LLM
- [x] Multiple tool_calls in one response dispatched in parallel via `ThreadPoolExecutor`; results returned in call order
- [x] Internal history grows across multiple `run()` calls on the same instance
- [x] Second `run()` call on same agent can see tool results from the first call in history
- [x] Remaining-iterations hint injected into context before each LLM call
- [x] Final-iteration hint changes to "provide your answer now" wording
- [x] When iterations exhausted and LLM still returns tool_calls: tools executed, then one final call made with tools unregistered so LLM is forced to respond
- [x] Unknown tool name returns `{"status": "error", "error": "unknown tool: <name>"}`

**Verify red:** `pytest tests/test_harness.py` — all tests fail

**Implement:**
- [x] `tools/base.py`
  - `BaseTool` ABC: `name: str`, `description: str`, `parameters: dict` (JSON Schema)
  - `execute(**kwargs) -> dict` — always returns a dict; on failure: `{"status": "error", "error": "...", "fallback": "..."}`
  - `to_llm_definition() -> dict` — `{"type": "function", "function": {"name", "description", "parameters"}}`
- [x] `agent/harness.py`
  - `SimpleReActAgent(llm_client: LLMClient, tools: list[BaseTool], system_prompt: str, max_iterations: int = 10)`
    - Initialises `self._history = ConversationHistory(system_prompt)` at construction
    - Builds tool definition list and name→tool routing map from `tools` at construction
    - `run(task: str) -> str`
    - Appends `task` as user message to `self._history`
    - Before each LLM call: injects `[Iterations remaining: N. ...]` note; on last iteration: `[Last iteration. Provide your final answer now.]`
    - Loop: LLM call → `stop` → append response to history, return content; `tool_calls` → dispatch all via `ThreadPoolExecutor`, append results to history → decrement counter → continue
    - If counter reaches 0 and LLM still returns tool_calls: execute them, append results, then call LLM once more with no tools registered (forced final response)

**Verify green:** `pytest tests/test_harness.py` — all tests pass

---

## Phase 4: Tools + Clients

Each tool has its own client and is independently testable. Unit tests mock HTTP — no live calls required.

### 4a: Weather (no auth — start here)

**Models:**
- `DailyWeather`: `date: str`, `temp_max: float`, `temp_min: float`, `precipitation_prob: int | None`, `weather_description: str`
- `WeatherForecast`: `city: str`, `days: list[DailyWeather]`, `mode: Literal["forecast"]`
- `ClimateSummary`: `city: str`, `month: str`, `days: list[DailyWeather]`, `mode: Literal["climate"]`, `note: str`

**Capture fixtures first:**
- [x] Geocode Tokyo → lat=35.6895, lon=139.69171, tz=Asia/Tokyo
- [x] Hit forecast endpoint for Tokyo, any 7-day window starting within the next 16 days → save raw JSON to `tests/fixtures/openmeteo_forecast_tokyo.json`
- [x] Hit climate endpoint for Tokyo, `start_date=2026-06-01`, `end_date=2026-06-30` → save raw JSON to `tests/fixtures/openmeteo_climate_tokyo_june.json` (note: correct subdomain is `climate-api.open-meteo.com`, not `climate.open-meteo.com`)

**Scaffold:**
- [x] `clients/weather_client.py` — `geocode()` returns hardcoded Tokyo coords; `get_forecast()` and `get_climate_average()` return `[]`
- [x] `tools/weather_forecast.py` — `WeatherForecastTool.execute()` returns `{"mode": "forecast", "days": []}`
- [x] `tools/climate_summary.py` — `ClimateSummaryTool.execute()` returns `{"mode": "climate", "days": []}`

**Tests (in `tests/test_tools.py`):**
- [x] `WeatherForecastTool.execute()` with mocked HTTP (from fixture) returns per-day temps and WMO descriptions
- [x] `ClimateSummaryTool.execute()` with mocked HTTP (from fixture) returns dict with `mode="climate"` and historical-average note
- [x] Geocoding failure returns `{"status": "error", ...}`

**Verify red:** run weather tests — all fail

**Implement:**
- [x] `clients/weather_client.py`
  - `geocode(city: str) -> tuple[float, float, str]` — lat, lon, timezone via Open-Meteo geocoding API
  - `get_forecast(lat, lon, timezone, start_date, end_date) -> list[dict]`
  - `get_climate_average(lat, lon, start_date, end_date) -> list[dict]`
  - WMO code → description mapping dict (full table from api_integrations.md)
- [x] `tools/weather_forecast.py` — `WeatherForecastTool(city, start_date, end_date)`
- [x] `tools/climate_summary.py` — `ClimateSummaryTool(city, month, year)`

**Verify green:** weather tests pass

### 4b: Currency (no auth)

**Models:**
- `CurrencyRate`: `from_currency: str`, `to_currency: str`, `rate: float`, `fetched_at: str`

**Capture fixtures first:**
- [x] Hit `https://api.frankfurter.app/latest?from=USD&to=INR,EUR,GBP,JPY` → save raw JSON to `tests/fixtures/frankfurter_usd_rates.json`

**Scaffold:**
- [x] `clients/currency_client.py` — `get_rate()` returns `1.0`
- [x] `tools/currency_convert.py` — `CurrencyConvertTool.execute()` returns `{"converted": 0.0, "rate": 1.0}`

**Tests:**
- [x] `CurrencyConvertTool.execute()` with mocked Frankfurter response (from fixture) returns correct converted amount
- [x] Second call within the same session reuses cached rate (no second HTTP call)

**Verify red:** currency tests fail

**Implement:**
- [x] `clients/currency_client.py` — `CurrencyClient`; session-cached rate; fetches `https://api.frankfurter.app/latest?from={X}&to={Y}`
- [x] `tools/currency_convert.py` — `CurrencyConvertTool(amount, from_currency, to_currency)`

**Verify green:** currency tests pass

### 4c: Web Search

**Capture fixtures first:**
- [x] Search `"Tokyo travel tips 2026 daily budget"` (depth=`advanced`) → saved to `tests/fixtures/tavily_destination_tokyo.json`
- [x] Search `"visa requirements Japan Indian passport 2026"` (depth=`basic`) → saved to `tests/fixtures/tavily_visa_japan.json`
- [x] Search `"best time to visit Tokyo weather seasons"` (depth=`basic`) → saved to `tests/fixtures/tavily_timing_tokyo.json`

**Scaffold:**
- [x] `clients/search_client.py` — `search()` returns `[]`
- [x] `tools/web_search.py` — `WebSearchTool.execute()` returns `{"results": []}`

**Tests:**
- [x] `WebSearchTool.execute()` with mocked `TavilyClient.search` (returning fixture data) returns formatted results list with title, url, content, score
- [x] Synthesised answer included when present in Tavily response
- [x] Session call counter increments on each call
- [x] Tool passes depth and max_results through to the client

**Verify red:** web search tests fail

**Implement:**
- [x] `clients/search_client.py` — `SearchClient(api_key)` wrapping `TavilyClient`; `_TavilyResponse`/`_TavilyResult` raw API models for early validation; `search(query, depth, max_results) -> dict`; session call counter with warning at 900
- [x] `tools/web_search.py` — `WebSearchTool`; `output_model = WebSearchOutput` (from `models/search.py`); validates output via `_validated_output`

**Verify green:** web search tests pass

### 4d: Flight Search (SerpApi Google Flights)

**Models:**
- `DateRange`: `label: str`, `start_date: str | None`, `end_date: str | None`; `from_string(s) -> DateRange` classmethod; `DateRange("any")` sentinel for time-insensitive KnowledgeState entries
- `FlightOption`: `airline`, `flight_number`, `price_usd` (round-trip total for rt searches), `stops`, `duration_min`, `departure`, `arrival`, `origin_iata`, `destination_iata`
- `FlightLegSummary`: `options: list[FlightOption]` (top-3 covering min-cost, min-duration, min-stops), `total_found: int`
- `FlightSearchOutput`: `trip_type: "one_way"|"round_trip"`, `outbound: FlightLegSummary`, `return_leg: FlightLegSummary | None`, `status: "ok"|"partial"`, `note: str`

**Capture fixtures first:**
- [x] Flight search: `BOM,NMI → NRT,HND`, one-way, departure 2026-07-13 → saved to `tests/fixtures/serpapi_flights_bom_nrt.json`
- [x] Departure date noted in `_fixture_meta` field inside the file

**Scaffold:**
- [x] `clients/serpapi_client.py` — `search_flights()` returns `[]`
- [x] `tools/flight_search.py` — `FlightSearchTool.execute()` returns `{"flights": []}`

**Tests:**
- [x] `FlightSearchTool.execute()` with mocked SerpApi response (from fixture) returns `FlightSearchOutput` with `outbound.options` containing `FlightOption`-shaped dicts
- [x] Stops derived correctly as `len(flights) - 1` per result
- [x] 429 response returns `{"status": "error", "fallback": "Flight search quota exceeded..."}`
- [x] Empty `best_flights` and `other_flights` returns `{"status": "error", "fallback": "No flights found..."}`

**Verify red:** flight tests fail

**Implement:**
- [x] `clients/serpapi_client.py` — `SerpApiClient(api_key)`; `search_flights(origin, destination, date, adults=1, currency="USD") -> list[dict]`; passes IATA codes directly, no separate lookup step; skips results missing `price` field
- [x] `tools/flight_search.py` — accepts `origin_airports: list[str]`, `destination_airports: list[str]`; joins with `","` before calling client

**Verify green:** flight tests pass

**Cleanup (deferred):**
- [ ] Simplify `FlightSearchTool` to `trip_type: "one_way" | "round_trip"` only — remove `"multi_city"` from the enum, validation, and execute path; remove `search_multi_city` from `SerpApiClient`; delete `serpapi_flights_multicity*.json` fixtures and all multi-city tests from `test_tools.py`

### 4f: Calculator

**Scaffold:**
- [x] `tools/calculate.py` — `CalculateTool.execute()` returns `{"result": 0.0, "label": "stub"}`

**Tests:**
- [x] `CalculateTool.execute(expression="(850 * 4 + 120) / 4", label="per-person flight")` returns `{"result": 880.0, "label": "per-person flight"}` (spec had wrong expected value; corrected to 880.0)
- [x] Multi-operator expressions with parentheses evaluated correctly
- [x] Expression containing a function call (`"sqrt(4)"`) returns `{"status": "error", ...}`
- [x] Expression containing attribute access (`"os.getcwd()"`) returns `{"status": "error", ...}`
- [x] Division by zero returns `{"status": "error", ...}`

**Verify red:** calculator tests fail

**Implement:**
- [x] `tools/calculate.py` — AST walker rejecting all non-arithmetic nodes; no `eval()` on unsafe input

**Verify green:** calculator tests pass

### 4e: File Write

**Scaffold:**
- [x] `tools/file_write.py` — `FileWriteTool.execute()` returns `{"status": "ok", "path": "stub"}` without touching the filesystem

**Tests:**
- [x] `FileWriteTool.execute()` writes file to disk and returns `{"status": "ok", "path": "..."}`
- [x] Writing to an already-existing filename produces `_v2`, `_v3`, etc. — never overwrites

**Verify red:** file write tests fail

**Implement:**
- [x] `tools/file_write.py` — `FileWriteTool(filename, content)`; auto-increments `_v{N}` on collision

**Verify green:** file write tests pass

---

## Phase 5: Specialist Agents

Each specialist is a **class** that owns one `SimpleReActAgent` instance (initialised with its system prompt and domain tools at construction) and exposes a `run(inputs) -> OutputModel` method. The agent's internal history persists across all calls to the specialist within the session. Raw API payloads never leave the specialist — only the structured output model is returned to the orchestrator wrapper.

Each specialist has a corresponding **wrapper tool** registered on the Orchestrator. The wrapper runs a pre-firing check against KnowledgeState, adjusts inputs on a partial cache hit, invokes the specialist, updates KnowledgeState, and returns a template-based summary to the Orchestrator LLM. See architecture.md L360–385 for the full wrapper pattern.

---

### Phase 5a: KnowledgeState Data Models

**Goal:** All data models for KnowledgeState defined and importable. No specialist logic yet.

**Models to implement** (see architecture.md for full field specs at given line numbers):
- [x] `UserContext(context, wordset, blocklist)` — see architecture.md L53–68; both `wordset` (positive-intent terms, blocklist excluded) and `blocklist` (negated entities) recomputed on each `context` update via NLTK pipeline + lightweight negation parser (regex on "not X", "avoid X", "no X", "skip X", "except X", "don't want X")
- [x] `DateRange` — L103–112; `from_string()` classmethod
- [x] `RouteKey(origin, destination)` — L114–116; frozen dataclass
- [x] `DestinationCandidate` — L118–131; `wordset` computed at creation via NLTK pipeline; `score` not stored
- [x] `Activity(name, tags, indoor, duration_min)` — see architecture.md Activity model
- [x] `DestinationResearch` — L138–154; includes `depth: Literal["light","full"]`
- [x] `StringWithAttribution(text, source_url)` — for factual claims with per-field source tracking
- [x] `CostWithAttribution(amount, source_url)` — wraps all cost fields in DestinationBudget
- [x] `DestinationBudget` — all USD, `dict[str, CostWithAttribution]` per category, `summary: str`
- [x] `TravelOption` — see architecture.md TravelOption model; `mode` discriminates flight vs. ground transport; `flight: FlightOption | None` for flight-specific detail
- [x] `DestinationKnowledge` — research, weather, budget
- [x] `RouteKnowledge(options: dict[DateRange, list[TravelOption]])` — `DateRange("any")` sentinel for time-insensitive options
- [x] `TimeSlot`, `ItineraryDay`, `Itinerary` — see architecture.md Itinerary models
- [x] `KnowledgeState` — all `update_*()` / `add_candidates()` methods including `update_route()`, `update_activities()`, `update_itinerary()`; `itineraries: dict[frozenset[str], Itinerary]`; `to_prompt_context(user_context, top_n)` implementing NLTK-based Jaccard scoring, destination budget range computation, and BFS-composed routes section (see architecture.md)

**Tests (`tests/test_knowledge_state.py`):**
- [x] `DateRange.from_string()` handles ISO range, single date, and natural language label
- [x] `KnowledgeState.add_candidates()` appends and never replaces
- [x] `KnowledgeState.to_prompt_context()` returns top-N candidates by recency + Jaccard score; normalises both components before combining
- [x] `KnowledgeState.to_prompt_context()` shows `(showing N of M)` when candidates exceed top_n
- [x] `KnowledgeState.update_*()` methods populate correct nested entries; re-calling with same key overwrites
- [x] `UserContext.wordset` updates when `context` changes; does not update otherwise
- [x] `UserContext.blocklist` populated from negation patterns — "not Thailand" → `{"thailand"}` in blocklist, "thailand" absent from `wordset`
- [x] `UserContext.blocklist` and `wordset` recomputed together on each `context` update; blocklist terms excluded from `wordset`

**Verify red → implement → verify green**

---

### Phase 5b: ExplorerSpecialist

**Contract:** see architecture.md L384–417

**Scaffold:**
- [x] `specialists/explorer.py` — `ExplorerSpecialist.run()` returns `[]`
- [x] `agent/prompts/explorer.py` — empty string

**Tests (`tests/test_specialists.py`):**
- [x] Stub LLM returns a valid candidate list; `run()` output parses to `list[DestinationCandidate]` with all fields populated including `wordset`
- [x] Stub LLM returns a `web_search` tool call then a final answer; assert `web_search` was dispatched
- [x] Wrapper pre-firing check: blocklisted candidate (name in `user_context.blocklist`) is excluded before Jaccard runs and never appears in cache hit counts or results
- [x] Wrapper pre-firing check: all K surviving candidates score above threshold → specialist not called; template summary returned
- [x] Wrapper pre-firing check: K < max_results surviving candidates match → specialist called with `max_results = max_results − K`; surviving candidates passed in prompt
- [x] Negative constraints from UserContext appear in the task string passed to the specialist
- [x] `specialist.run()` raises an exception → wrapper catches it, returns error string as tool result, `knowledge.add_candidates()` not called

Note: wrapper exception handling is tested here as the canonical example; the same pattern applies to every specialist wrapper — each Phase 5x adds this test.

**Verify red:** `pytest tests/test_specialists.py -k explorer` — all fail

**Implement:**
- [x] `agent/prompts/explorer.py` — instructs agent to use `web_search`, not repeat candidates already in the current list, respect negative constraints, return structured `DestinationCandidate` list
- [x] `specialists/explorer.py` — `ExplorerSpecialist(llm_client, tools)`; `run(query, max_results, existing_candidates) -> list[DestinationCandidate]`
- [x] Wrapper tool for ExplorerSpecialist — pre-firing check using `EXPLORER_CACHE_THRESHOLD = 0.6`; calls `knowledge.add_candidates()`; returns template summary

**Verify green:** `pytest tests/test_specialists.py -k explorer` — all pass

---

### Phase 5c: WeatherSpecialist

**Contract:** see architecture.md L474–523

**Scaffold:**
- [x] `specialists/weather.py` — `WeatherSpecialist.run()` returns empty `WeatherOutput`
- [x] `agent/prompts/weather.py` — empty string
- [x] `tools/slice_weather_range.py` — `SliceWeatherRangeTool.execute()` returns `{"status": "ok", "days": []}`

**Tests (`tests/test_specialists.py`):**
- [x] Stub returns `slice_weather_range` tool call (subset case); tool correctly slices existing `WeatherOutput` days and calls `update_weather()` with new entry; no `weather_forecast`/`climate_summary` dispatched
- [x] Stub returns `slice_weather_range` + `weather_forecast` as parallel tool calls (augment case); wrapper merges the two `WeatherOutput.days` arrays in Python and calls `update_weather()` with combined entry; no extra LLM call
- [x] Wrapper pre-firing check: exact key exists → specialist not called; template summary returned with correct avg stats and "historical avg" label for climate mode
- [x] Wrapper template: forecast summary includes avg high/low and precipitation probability; climate summary includes "historical avg" label and precipitation sum

Note: which tool the LLM selects (mode selection, when to use `slice_weather_range`) depends on the prompt and belongs in evaluation, not the test suite.

**Verify red → implement → verify green**

**Implement:**
- [x] `tools/slice_weather_range.py` — reads existing `WeatherOutput` from KnowledgeState, slices or merges days, calls `update_weather()` with new entry
- [x] `agent/prompts/weather.py` — instructs specialist to check existing date ranges before fetching, use `slice_weather_range` for subsets/augmentation, select mode from date range
- [x] `specialists/weather.py` — `WeatherSpecialist(llm_client, tools)`; `run(destination, date_range) -> WeatherOutput`
- [x] Wrapper tool for WeatherSpecialist — exact key pre-firing check; calls `update_weather()`; template summary with mode-appropriate stats

---

### Phase 5d: DestinationResearchSpecialist

**Contract:** see architecture.md — DestinationResearchSpecialist section

**Scaffold:**
- [x] `specialists/destination_research.py` — `DestinationResearchSpecialist.run()` returns empty `DestinationResearch`
- [x] `agent/prompts/destination_research.py` — empty string

**Tests (`tests/test_specialists.py`):**
- [x] Stub LLM returns a valid `DestinationResearch`; `run()` output has `summary` populated alongside all depth-appropriate fields
- [x] Stub LLM returns a `web_search` tool call then a final answer; assert `web_search` was dispatched
- [x] Wrapper pre-firing check: light cache exists + `depth="light"` → specialist not called; `research.summary` returned verbatim
- [x] Wrapper pre-firing check: full cache exists + `depth="light"` → specialist not called; `research.summary` returned verbatim (full is superset)
- [x] Wrapper pre-firing check: light cache exists + `depth="full"` → specialist called with `max_iterations=3` (upgrade)
- [x] Wrapper pre-firing check: full cache exists + `depth="full"` → specialist called with `max_iterations=4` (pass-through; specialist self-directs)
- [x] Wrapper calls `knowledge.update_research()` with typed `DestinationResearch` result after specialist returns

Note: how many searches the specialist conducts per depth mode, context drift refresh decisions, and summary content quality depend on the prompt — these belong in evaluation, not the test suite.

**Verify red:** `pytest tests/test_specialists.py -k destination_research` — all fail

**Implement:**
- [x] `agent/prompts/destination_research.py` — instructs specialist to conduct light vs. full searches per depth instruction, generate `summary` alongside structured fields in one response, use UserContext for nationality (visa profiles) and interest tailoring
- [x] `specialists/destination_research.py` — `DestinationResearchSpecialist(llm_client, tools)`; `run(destination, depth, user_context) -> DestinationResearch`
- [x] Wrapper tool for DestinationResearchSpecialist — pre-firing check per five-case table; sets `max_iterations` accordingly; calls `knowledge.update_research()`; returns `research.summary` verbatim as orchestrator summary

**Verify green:** `pytest tests/test_specialists.py -k destination_research` — all pass

---

### Phase 5e: TransportationSpecialist

**Contract:** see architecture.md — TransportationSpecialist section

**Prerequisite cleanup from Phase 4d:**
- [ ] Revise `FlightSearchOutput` to `FlightLegSummary` + revised `FlightSearchOutput` structure (see Phase 4d models above); update `FlightSearchTool` top-3 selection logic; update tests accordingly

**Scaffold:**
- [ ] `specialists/transportation.py` — `TransportationSpecialist.run()` returns `[]`
- [ ] `agent/prompts/transportation.py` — empty string

**Tests (`tests/test_specialists.py`):**
- [ ] Stub LLM returns a valid `list[TravelOption]`; `run()` output parses with flight and transfer options present
- [ ] Stub LLM returns parallel `flight_search` calls for two routes; assert parallel dispatch
- [ ] Stub LLM returns `web_search` for transfer options after `flight_search`; assert both dispatched
- [ ] Wrapper pre-firing check: BFS finds complete path for all routes → specialist not called; composed template returned
- [ ] Wrapper pre-firing check: BFS finds partial path for one route → specialist called with partial edges in task context
- [ ] Wrapper groups TravelOptions by `(origin, destination)`; calls `update_route()` per group with correct `DateRange` — `DateRange("any")` for non-flight modes
- [ ] Round-trip: `mode="flight/return"` options stored under reversed RouteKey
- [ ] `max_iterations` set to `min(2 + len(missing_routes), 5)`

Note: IATA resolution strategy, round-trip vs. one-way decision, and ground transport identification depend on the prompt — these belong in evaluation, not the test suite.

**Verify red:** `pytest tests/test_specialists.py -k transportation` — all fail

**Implement:**
- [ ] `models/transportation.py` — `TravelOption` (with `flight: FlightOption | None`)
- [ ] `agent/prompts/transportation.py` — instructs specialist to resolve city names to IATA codes via `web_search`, ensure composed path starts and ends at Orchestrator city names, store departure and arrival transfers, use `trip_type="round_trip"` when applicable, fall back to ground transport search when flights unavailable or unnatural (short overland corridors)
- [ ] `specialists/transportation.py` — `TransportationSpecialist(llm_client, tools)`; `run(routes, user_context) -> list[TravelOption]`
- [ ] Wrapper tool for TransportationSpecialist — BFS pre-firing check; sets `max_iterations`; groups output by RouteKey; calls `update_route()` per group; BFS compose for template summary

**Verify green:** `pytest tests/test_specialists.py -k transportation` — all pass

---

### Phase 5f: BudgetSpecialist

**Contract:** see architecture.md — BudgetSpecialist section

**Scaffold:**
- [ ] `specialists/budget.py` — `BudgetSpecialist.run()` returns empty `BudgetSpecialistOutput`
- [ ] `agent/prompts/budget.py` — empty string

**Tests (`tests/test_specialists.py`):**
- [ ] Stub LLM returns valid `BudgetSpecialistOutput` with `breakdown` populated; `run()` output parses correctly
- [ ] Stub LLM returns parallel `web_search` calls for accommodation and food costs in one iteration; assert parallel dispatch
- [ ] Stub LLM returns `currency_convert` then `calculate` calls in sequence; assert both dispatched
- [ ] Wrapper calls `update_destination_budget()` when `result.destination_budget` is not `None`; skips call when `None`
- [ ] Wrapper passes existing `DestinationBudget` snapshot + TravelOption costs (excluding `mode="flight/return"`) in task context

Note: whether the specialist skips `web_search` when `DestinationBudget` is already present depends on the prompt — belongs in evaluation, not the test suite.

Note: cost estimation quality, currency selection, and arithmetic expression construction depend on the prompt — these belong in evaluation, not the test suite.

**Verify red:** `pytest tests/test_specialists.py -k budget` — all fail

**Implement:**
- [ ] `models/budget.py` — `BudgetSpecialistOutput(destination_budget: DestinationBudget | None, breakdown: str)`
- [ ] `agent/prompts/budget.py` — instructs specialist to use parallel `web_search` for missing cost categories, route all arithmetic through `calculate`, skip `mode="flight/return"` TravelOptions when summing route costs, output ranges (low/high) rather than point estimates
- [ ] `specialists/budget.py` — `BudgetSpecialist(llm_client, tools)`; `run(query, context) -> BudgetSpecialistOutput`
- [ ] Wrapper tool for BudgetSpecialist — no pre-firing check; extracts DestinationBudget + TravelOptions from KnowledgeState for context; calls `update_destination_budget()` if new data returned; returns `result.breakdown` verbatim

**Verify green:** `pytest tests/test_specialists.py -k budget` — all pass

---

### Phase 5g: ItineraryPlannerSpecialist

**Contract:** see architecture.md — ItineraryPlannerSpecialist section

**Scaffold:**
- [ ] `specialists/itinerary_planner.py` — `ItineraryPlannerSpecialist.run()` returns empty `ItineraryPlannerOutput`
- [ ] `agent/prompts/itinerary_planner.py` — empty string

**Tests (`tests/test_specialists.py`):**
- [ ] Stub LLM returns valid `ItineraryPlannerOutput`; `run()` output parses with `itinerary.days` populated and `day_num` sequential from 1
- [ ] Stub LLM returns parallel `web_search` calls for multiple venues in one iteration; assert parallel dispatch
- [ ] Wrapper calls `update_itinerary()` with `frozenset(destinations)` key
- [ ] Wrapper calls `update_activities(destination, activities)` for each non-empty entry in `result.activity_updates`; skips call when list is empty
- [ ] Second `run()` call on same instance includes prior itinerary in history (refinement path)
- [ ] `TimeSlot.is_alternative=True` slots in a day's list all follow a non-alternative slot; no two consecutive `is_alternative=True` slots without a primary between them (structural validity, not prompt behavior)

Note: scheduling rule application (arrival/departure/transit day structure, weather-aware slot selection, festival incorporation) depends on the prompt — these belong in evaluation, not the test suite.

**Verify red:** `pytest tests/test_specialists.py -k itinerary` — all fail

**Implement:**
- [ ] `models/itinerary.py` — `TimeSlot`, `ItineraryDay`, `Itinerary`, `ItineraryPlannerOutput`
- [ ] `agent/prompts/itinerary_planner.py` — instructs specialist to use parallel `web_search` per destination block for venues/hours, apply scheduling rules (arrival/departure/transit days, weather-aware primary/alternative slots via `is_alternative` flag, ≤2 alternatives per primary slot, ≤3 alternative slots per day), assume reasonable intra-city transit constants, enrich `Activity` objects with `duration_min` and `indoor` when researching venues, incorporate festivals and closures from DestinationResearch
- [ ] `specialists/itinerary_planner.py` — `ItineraryPlannerSpecialist(llm_client, tools)`; `run(query, context) -> ItineraryPlannerOutput`
- [ ] Wrapper tool for ItineraryPlannerSpecialist — no pre-firing check; passes UserContext + DestinationResearch + WeatherOutput from KnowledgeState as appended context; calls `update_itinerary()` and `update_activities()` per result; returns template summary

**Verify green:** `pytest tests/test_specialists.py -k itinerary` — all pass

---

### Phase 5h: ArtifactSpecialist

**Contract:** see architecture.md — ArtifactSpecialist section

**Scaffold:**
- [ ] `specialists/artifact.py` — `ArtifactSpecialist.run()` returns empty `ArtifactOutput`
- [ ] `agent/prompts/artifact.py` — empty string
- [ ] `tools/get_compiled.py` — one file; all `Get*CompiledTool` classes return `""` stubs
- [ ] `tools/get_itinerary.py` — `GetItineraryTool.execute()` returns `""`
- [ ] `tools/self_critique.py` — `SelfCritiqueTool.execute()` returns `""`

**Tests (`tests/test_specialists.py`):**
- [ ] Stub LLM calls parallel compiled tools then `self_critique` then `file_write`; assert all dispatched
- [ ] `GetResearchCompiledTool("Tokyo")` returns structured Markdown including vibe, attractions, safety with `[source](url)`, neighbourhoods with `[source](url)`, activities with `[source](url)`, summary; returns informative error string when absent
- [ ] `GetBudgetCompiledTool("Tokyo")` returns all cost categories with `[source](url)` and summary; returns error string when absent
- [ ] `GetWeatherCompiledTool("Tokyo", "June 2026")` returns serialised `WeatherOutput.days`; returns error string when absent
- [ ] `GetRouteCompiledTool("Mumbai", "Tokyo", "Jul 2026")` returns BFS-composed TravelOptions with source links; returns error string when absent
- [ ] `GetCandidatesCompiledTool()` returns all candidates with rationale and `[source](url)`
- [ ] `GetItineraryTool(["Tokyo"])` returns day-by-day with `is_alternative` slots marked; returns error string when absent
- [ ] `SelfCritiqueTool` makes one LLM call with `content` + `query` only (no skeleton); returns non-empty critique string
- [ ] Draft is passed as argument to `self_critique`, not returned as standalone message content
- [ ] `ArtifactOutput.file_path` matches actual path returned by `file_write`
- [ ] Wrapper injects `to_prompt_context()` skeleton in task context; no KnowledgeState write after run

Note: draft quality, critique usefulness, and source link density depend on the prompt — these belong in evaluation, not the test suite.

**Verify red:** `pytest tests/test_specialists.py -k artifact` — all fail

**Implement:**
- [ ] `models/artifact.py` — `ArtifactOutput(file_path: str)`
- [ ] `tools/get_compiled.py` — `GetResearchCompiledTool(knowledge_state)`, `GetBudgetCompiledTool(knowledge_state)`, `GetWeatherCompiledTool(knowledge_state)`, `GetRouteCompiledTool(knowledge_state)`, `GetCandidatesCompiledTool(knowledge_state)`; each serialises the relevant model to structured data (JSON or plain text) with source URLs co-located next to attributed fields; returns informative error string on miss (never raises)
- [ ] `tools/get_itinerary.py` — `GetItineraryTool(knowledge_state)`; looks up `itineraries[frozenset(destinations)]`; serialises `Itinerary` to structured day-by-day string with `is_alternative` slots clearly marked
- [ ] `tools/self_critique.py` — `SelfCritiqueTool(llm_client)`; focused LLM call with `content` + `query`; no KnowledgeState access; returns structured critique
- [ ] `agent/prompts/artifact.py` — instructs specialist to: read skeleton to determine available data, call compiled tools in parallel for needed sections, embed draft as `content` arg to `self_critique` (never output draft as standalone message), apply critique then call `file_write`, weave inline `[source](url)` links from attributed fields, append standard footer
- [ ] `specialists/artifact.py` — `ArtifactSpecialist(llm_client, tools)`; `run(query, context) -> ArtifactOutput`
- [ ] Wrapper tool for ArtifactSpecialist — no pre-firing check; injects `knowledge.to_prompt_context()` in task context; constructs all compiled tools and `GetItineraryTool` with `knowledge_state` reference; no KnowledgeState write; returns file path as summary

**Verify green:** `pytest tests/test_specialists.py -k artifact` — all pass

---

## Phase 6: Orchestrator

**Goal:** TravelAgent orchestrator. Uses `SimpleReActAgent` where the registered tools are specialist wrapper tools plus `update_user_context`. Owns session state (`UserContext`, `KnowledgeState`). Parallel specialist calls happen naturally when the LLM returns multiple tool_calls in one response.

**Models:** All KnowledgeState models and `UserContext` are defined and tested in Phase 5a — imported here, not redefined.

**Scaffold:**
- [ ] `agent/orchestrator.py` — `Orchestrator.turn()` returns `"stub"` immediately
- [ ] `agent/prompts/orchestrator.py` — empty string

**Tests (`tests/test_orchestrator.py`) — stub `LLMClient`, fast, always run:**
- [ ] Stub returns `update_user_context` tool call; assert `UserContext.context` updated and `wordset`/`blocklist` recomputed via NLTK
- [ ] Stub returns a specialist tool call; assert wrapper `execute()` calls `specialist.run()` and calls the matching `knowledge.update_*()` method
- [ ] Stub returns multiple tool_calls in one response; assert all specialists dispatched in parallel (confirms wiring — parallel dispatch proven in harness tests)
- [ ] Each `turn()` call builds task with current `UserContext.context` + `knowledge.to_prompt_context()` + user input
- [ ] Second `turn()` on same instance includes prior exchange in agent's internal history

Note: exception handling in wrappers (catching `specialist.run()` failures, returning error string, leaving KnowledgeState unchanged) is tested per specialist in Phase 5x tests, not here. Clarification logic, `update_user_context` call timing, query routing, and parallel call selection depend on the orchestrator prompt — tested during prompt evaluation.

Note: clarification logic, `update_user_context` call timing, query routing, and parallel call selection depend on the orchestrator prompt — tested during prompt evaluation, not here.

**Verify red:** `pytest tests/test_orchestrator.py` — all tests fail

**Implement:**
- [ ] `tools/update_user_context.py` — `UpdateUserContextTool(user_context: UserContext)`; sets `user_context.context = new_context`; triggers NLTK recomputation of `wordset` and `blocklist`; returns `{"status": "ok"}`
- [ ] `agent/prompts/orchestrator.py` — covers: call `update_user_context` first when user provides new trip information; query type recognition; when to clarify vs. act; which specialists to call and when in parallel; depth escalation rules
  - **UserContext format note:** When writing or updating `UserContext.context`, negative constraints must be expressed as distinct, explicit phrases that the negation regex can match: "not Thailand", "avoid beaches", "no nightlife" — not buried in prose like "I'm not really a beach person". This ensures `blocklist` is correctly populated and scoring/exclusion work as intended.
  - **Explorer query note:** When calling the ExplorerWrapperTool, the `query` argument must be a positive-intent rewrite of the user's request — affirmative signals only, negatives stripped out. Example: "trip in SEA, not too heavy on nightlife, more nature focused" → `query="nature focused trip in South East Asia"`. Negatives are handled via `blocklist`; including them in the query string corrupts Jaccard scoring.
- [ ] `agent/orchestrator.py`
  - `Orchestrator(llm_client: LLMClient, specialists: dict[str, SpecialistClass])`
  - State: `user_context: UserContext`, `knowledge: KnowledgeState`
  - Builds wrapper tools at construction: for each specialist, a `BaseTool` whose `execute()` runs the pre-firing check, calls `specialist.run()`, calls `knowledge.update_*()`, catches exceptions and returns error string on failure, returns plain-text summary. ArtifactSpecialist wrapper additionally constructs `Get*CompiledTool(knowledge)` and `GetItineraryTool(knowledge)` instances.
  - Also registers `UpdateUserContextTool(user_context)` in the tool list
  - Owns one `SimpleReActAgent(llm_client, wrapper_tools + [update_user_context_tool], ORCHESTRATOR_PROMPT, max_iterations=8)` instance
  - `turn(user_input: str) -> str`
    1. Build task: `f"UserContext:\n{user_context.context}\n\nKnowledgeState:\n{knowledge.to_prompt_context()}\n\nUser: {user_input}"`
    2. Return `self._agent.run(task)` — all updates (context, KnowledgeState) happen as tool side-effects during execution

**Verify green:** `pytest tests/test_orchestrator.py` — all tests pass

---

## Phase 7: CLI + Polish

### 7a: Wiring

- [ ] **NLTK data** — add `ensure_nltk_data()` in `main.py` that calls `nltk.download()` for `stopwords`, `wordnet`, `punkt_tab` on first run (idempotent; skips if already present)
- [ ] **Startup validation** — check all required env vars before entering the loop; print a clear error and exit if any are missing (fail fast, not mid-conversation)
- [ ] **Construction order in `main.py`:**
  1. `Settings` from `.env`
  2. Clients: `LLMClient`, `SerpApiClient`, `WeatherClient`, `CurrencyClient`, `SearchClient`
  3. Session state: `KnowledgeState()`, `UserContext()`
  4. Shared tools: `WebSearchTool`, `FlightSearchTool`, `WeatherForecastTool`, `ClimateSummaryTool`, `CurrencyConvertTool`, `CalculateTool`, `FileWriteTool`
  5. KnowledgeState-aware tools: `SliceWeatherRangeTool(knowledge)`, `GetResearchCompiledTool(knowledge)`, `GetBudgetCompiledTool(knowledge)`, `GetWeatherCompiledTool(knowledge)`, `GetRouteCompiledTool(knowledge)`, `GetCandidatesCompiledTool(knowledge)`, `GetItineraryTool(knowledge)`, `SelfCritiqueTool(llm_client)`
  6. Specialists: each with the tool set defined in their Phase 5x contract
  7. `Orchestrator(llm_client, user_context, knowledge, specialists)`
- [ ] **REPL loop:** `input("You: ")` → `orchestrator.turn()` → print response; graceful `KeyboardInterrupt` exit with goodbye message; skip empty input

### 7b: Output

- [ ] **Spinner** — `rich` status indicator during `orchestrator.turn()` so the user knows the agent is working
- [ ] **Markdown rendering** — Orchestrator responses are LLM-generated Markdown; render with `rich.Markdown` so headers, tables, lists, and code blocks display correctly
- [ ] **Errors in red** — if `orchestrator.turn()` raises an uncaught exception, print the error in red and continue the loop rather than crashing
- [ ] **Artifact save confirmation** — when a file is written, print the full path in a distinct style so the user can find it
- [ ] **`--debug` flag** — when set, print each tool call (name + truncated args) and result (first 200 chars) to stderr as the session progresses; useful for prompt iteration without cluttering normal output

### 7c: Finish line

- [ ] Update `README.md`: reflect current setup instructions (SerpApi not Amadeus), full list of env vars, first-run walkthrough
- [ ] Manual end-to-end test: "Mumbai → Tokyo, late June, ₹2.5L" → verify full response including weather, flights, budget, itinerary, and saved artifact file

---

## Dependency Order

```
config/settings.py
  └── clients/llm_client.py
        ├── agent/session.py
        └── tools/base.py
              ├── tools/* (each independently testable)
              │     └── clients/* (each independently testable)
              └── agent/harness.py
                    └── specialists/* (each independently testable)
                          └── agent/orchestrator.py
                                └── main.py
```
