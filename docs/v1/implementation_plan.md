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
- [x] Write `src/requirements.txt`: `httpx`, `pydantic`, `pydantic-settings`, `python-dotenv`, `tavily-python`, `rich`, `pytest`, `pytest-mock`
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
- `DateRange`: `label: str`, `start_date: str | None`, `end_date: str | None`; `from_string(s) -> DateRange` classmethod
- `TripLeg`: `origin: str`, `destination: str`, `date: str`
- `FlightDetails`: `airline: str`, `price_usd: float`, `stops: int`, `duration_min: int`, `departure: str`, `arrival: str`, `flight_number: str`

**Capture fixtures first:**
- [x] Flight search: `BOM,NMI → NRT,HND`, one-way, departure 2026-07-13 → saved to `tests/fixtures/serpapi_flights_bom_nrt.json`
- [x] Departure date noted in `_fixture_meta` field inside the file

**Scaffold:**
- [x] `clients/serpapi_client.py` — `search_flights()` returns `[]`
- [x] `tools/flight_search.py` — `FlightSearchTool.execute()` returns `{"flights": []}`

**Tests:**
- [x] `FlightSearchTool.execute()` with mocked SerpApi response (from fixture) returns list of `FlightDetails`-shaped dicts
- [x] Stops derived correctly as `len(flights) - 1` per result
- [x] 429 response returns `{"status": "error", "fallback": "Flight search quota exceeded..."}`
- [x] Empty `best_flights` and `other_flights` returns `{"status": "error", "fallback": "No flights found..."}`

**Verify red:** flight tests fail

**Implement:**
- [x] `clients/serpapi_client.py` — `SerpApiClient(api_key)`; `search_flights(origin, destination, date, adults=1, currency="USD") -> list[dict]`; passes IATA codes directly, no separate lookup step; skips results missing `price` field
- [x] `tools/flight_search.py` — accepts `origin_airports: list[str]`, `destination_airports: list[str]`; joins with `","` before calling client

**Verify green:** flight tests pass

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

```python
class WeatherSpecialist:
    def __init__(self, llm_client: LLMClient, tools: list[BaseTool]):
        self._agent = SimpleReActAgent(llm_client, tools,
                                       system_prompt=WEATHER_PROMPT, max_iterations=1)

    def run(self, city: str, date_range: str) -> WeatherForecast | ClimateSummary:
        task = f"Get weather for {city} in {date_range}"
        result_str = self._agent.run(task)
        return parse_weather_result(result_str)
```

**Models introduced (per specialist):**
- Explorer: `DestinationCandidate(name, country, vibe_tags, budget_fit, rationale, source_url)`
- DestinationResearch: `DestinationResearch(name, country, depth, vibe, budget_tier, top_attractions, daily_cost_usd, visa_summary, safety_summary, festivals, neighbourhoods)`
- Transportation: uses `FlightDetails` from Phase 4
- Weather: uses `WeatherForecast | ClimateSummary` from Phase 4
- Budget: `CostEstimate(low, high, currency)`, `BudgetBreakdown(destination, flights, accommodation, daily_expenses, total, budget_delta)`; uses `calculate` tool for all arithmetic — no LLM mental math
- ItineraryPlanner: `ItinerarySlot(time, activity, duration_min, notes)`, `ItineraryDay(date, weather_note, slots)`, `Itinerary(destination, days)`
- Artifact: `str` (file path written)

**Scaffold:**
- [ ] Each specialist class created with `run()` returning a hardcoded empty output model (e.g., `WeatherSpecialist.run()` returns `WeatherForecast(city="", days=[], mode="forecast")`)
- [ ] Prompt files created as empty strings in `agent/prompts/`

**Tests (`tests/test_specialists.py`):**
- [ ] Each specialist: stub `LLMClient` returns plausible structured response; assert output parses to the correct model
- [ ] DestinationResearchAgent `depth="light"`: exactly 1 `web_search` call made
- [ ] DestinationResearchAgent `depth="full"`: 3–4 `web_search` calls made
- [ ] TransportationAgent: IATA resolution call made before flight search call
- [ ] WeatherAgent: dates within 16 days → `weather_forecast` tool called; month-only input → `climate_summary` tool called
- [ ] BudgetAgent: `budget_delta` is negative when trip costs exceed user budget, positive otherwise
- [ ] ItineraryPlannerAgent: day 1 has arrival-only activities, last day has morning slot only

**Verify red:** `pytest tests/test_specialists.py` — all tests fail

**Implement (in order of increasing complexity):**
- [ ] `agent/prompts/weather.py` + `specialists/weather.py` → `WeatherForecast | ClimateSummary`
- [ ] `agent/prompts/budget.py` + `specialists/budget.py` → `BudgetBreakdown`
- [ ] `agent/prompts/explorer.py` + `specialists/explorer.py` → `list[DestinationCandidate]`
- [ ] `agent/prompts/destination_research.py` + `specialists/destination_research.py` → `DestinationResearch`
- [ ] `agent/prompts/transportation.py` + `specialists/transportation.py` → `list[FlightDetails]`
- [ ] `agent/prompts/itinerary_planner.py` + `specialists/itinerary_planner.py` → `Itinerary`
- [ ] `agent/prompts/artifact.py` + `specialists/artifact.py` → `str`

**Verify green:** `pytest tests/test_specialists.py` — all tests pass

---

## Phase 6: Orchestrator

**Goal:** TravelAgent orchestrator. Uses `SimpleReActAgent` where the registered tools are specialist wrapper tools. Owns session state (UserContext, KnowledgeState). Parallel specialist calls happen naturally when the LLM returns multiple tool_calls in one response.

**Models introduced:**
- `DateRange` already defined in Phase 4d — imported here
- `DestinationKnowledge(name, country, research, weather: dict[DateRange, WeatherSummary], flights: dict[DateRange, list[FlightDetails]], budget, depth: "light"|"full")`
- `KnowledgeState(destinations: dict[str, DestinationKnowledge])` with typed update methods:
  - `update_research(destination, result: DestinationResearch)`
  - `update_weather(destination, date_range: DateRange, result: WeatherSummary)`
  - `update_flights(destination, date_range: DateRange, results: list[FlightDetails])`
  - `update_budget(destination, result: BudgetBreakdown)`

**Scaffold:**
- [ ] `agent/orchestrator.py` — `Orchestrator.turn()` returns `"stub"` immediately
- [ ] `KnowledgeState` created with all `update_*()` methods as no-ops and `summary()` returning `""`
- [ ] `agent/prompts/orchestrator.py` — empty string

**Tests (`tests/test_orchestrator.py`):**
- [ ] "Is Morocco safe?" → no specialist calls if `DestinationResearch` already in KnowledgeState; specialists called if not
- [ ] "I want to travel somewhere nice" → LLM returns clarifying question, no tool calls
- [ ] "Mumbai to Tokyo, late June, ₹2.5L" → LLM returns multiple tool_calls (parallel) in first iteration
- [ ] Optional specialist failure: orchestrator continues, gap noted in KnowledgeState
- [ ] Synthesis uses KnowledgeState summaries passed as context, not raw specialist tool outputs
- [ ] UserContext accumulates across turns; never reset
- [ ] Clarification cap: at most one clarification round per message; second vague answer proceeds with stated assumption

**Verify red:** `pytest tests/test_orchestrator.py` — all tests fail

**Implement:**
- [ ] `agent/prompts/orchestrator.py` — covers: query type recognition, when to clarify vs. act, which specialists to call and when to call them in parallel, depth escalation rules
- [ ] `agent/orchestrator.py`
  - `Orchestrator(llm_client: LLMClient, specialists: dict[str, <SpecialistClass>])`
  - State: `user_context: str`, `knowledge: KnowledgeState`
  - Owns one `SimpleReActAgent(llm_client, wrapper_tools, ORCHESTRATOR_PROMPT, max_iterations=8)` instance; its internal history IS the full session log
  - Wrapper tool pattern: for each specialist, construct a `BaseTool` whose `execute()` calls `specialist.run()`, then calls the matching `knowledge.update_*()`, then returns a plain-text summary — these wrapper tools are the `tools` list passed to the orchestrator's `SimpleReActAgent`
  - `turn(user_input: str) -> str`
    1. Update `user_context` string (small focused LLM call or string append)
    2. Build task: `f"Context: {user_context}\n\nKnowledge summary:\n{knowledge.summary()}\n\nUser: {user_input}"`
    3. `response = self._agent.run(task)` — specialist wrapper tools update KnowledgeState as side-effects during execution
    4. Return `response`

**Verify green:** `pytest tests/test_orchestrator.py` — all tests pass

---

## Phase 7: CLI + Polish

- [ ] Wire `src/main.py`: initialize all clients and specialists, create `Orchestrator`, `input()` → `turn()` → `print()` loop, graceful Ctrl-C exit
- [ ] `rich` output: spinner during specialist calls, budget as `rich.Table`, flights in a panel, errors in red
- [ ] `--debug` flag: print specialist tool calls and results to stderr
- [ ] Update `README.md`: setup instructions, first-run walkthrough, example session transcript
- [ ] Manual end-to-end test: "Mumbai → Tokyo, late June, ₹2.5L" → full response including saved itinerary file

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
