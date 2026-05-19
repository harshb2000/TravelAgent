# API Integrations

This document covers every external API used in TravelAgent v1: how to obtain credentials, which endpoints are called, rate limits, known error conditions, and how to test without live API calls.

---

## LLM Provider (OpenAI-compatible)

TravelAgent uses no LLM SDK. The agent loop makes raw HTTP calls to any OpenAI-compatible `/chat/completions` endpoint, using the tool use (function calling) feature of the Chat Completions API.

### Configuration

```env
LLM_BASE_URL=https://api.anthropic.com/v1    # Change to swap providers
LLM_API_KEY=your_key_here
LLM_MODEL=claude-sonnet-4-6
```

### Supported Providers

| Provider | `LLM_BASE_URL` | Notes |
|---|---|---|
| Anthropic | `https://api.anthropic.com/v1` | Requires `anthropic-version: 2023-06-01` header |
| Groq | `https://api.groq.com/openai/v1` | Fast inference, free tier |
| Together.ai | `https://api.together.xyz/v1` | Many open models |
| Ollama (local) | `http://localhost:11434/v1` | No key needed; set `LLM_API_KEY=none` |

### Key Endpoints

```
POST {LLM_BASE_URL}/chat/completions
```

### Request Format (tool use)

```json
{
  "model": "claude-sonnet-4-6",
  "messages": [...],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "search_flights",
        "description": "...",
        "parameters": { "type": "object", "properties": {...}, "required": [...] }
      }
    }
  ],
  "tool_choice": "auto",
  "max_tokens": 4096
}
```

### Response: Tool Call

When the model wants to call a tool, `finish_reason` is `"tool_calls"` and `message.tool_calls` contains an array of calls to dispatch.

### Response: Final Answer

When `finish_reason` is `"stop"`, `message.content` is the final text response to show the user.

### Rate Limits / Cost

Varies by provider. For Anthropic: Sonnet tier is ~$3/M input tokens, $15/M output. For development, use Groq free tier (60 requests/min) or Ollama locally.

---

## SerpApi Google Flights API (Flight Search)

### Getting Credentials

1. Register at [serpapi.com](https://serpapi.com)
2. Copy your **API Key** from the dashboard
3. Free tier: 250 searches/month — sufficient for development and testing

```env
SERPAPI_API_KEY=your_serpapi_key
```

### Auth

API key passed as a query parameter on every request — no OAuth flow, no token refresh.

### Endpoint

```
GET https://serpapi.com/search
  ?engine=google_flights
  &api_key={SERPAPI_API_KEY}
  &...
```

### Request Parameters

| Parameter | Required | Format | Example | Notes |
|---|---|---|---|---|
| `engine` | yes | string | `"google_flights"` | Fixed value |
| `departure_id` | yes | IATA code | `"BOM"` | 3-letter uppercase; comma-separate for multi-airport cities |
| `arrival_id` | yes | IATA code | `"NRT"` | Same format |
| `outbound_date` | yes | YYYY-MM-DD | `"2026-06-20"` | |
| `type` | no | integer | `2` | `1`=round-trip (default), `2`=one-way |
| `return_date` | if round-trip | YYYY-MM-DD | `"2026-06-30"` | Required when `type=1` |
| `adults` | no | integer | `1` | Default 1 |
| `travel_class` | no | integer | `1` | `1`=Economy, `2`=Premium Economy, `3`=Business, `4`=First |
| `currency` | no | ISO 4217 | `"USD"` | Default USD |
| `stops` | no | integer | `0` | `0`=any, `1`=nonstop, `2`=≤1 stop, `3`=≤2 stops |
| `include_hidden_flights` | no | boolean | `true` | Include results beyond Google's initial load |

No separate IATA lookup step required — pass IATA codes directly.

### Key Response Fields

```
best_flights[].price                              → integer, total price in selected currency
best_flights[].total_duration                     → integer, total trip duration in minutes
best_flights[].flights[].airline                  → string, e.g. "Japan Airlines"
best_flights[].flights[].flight_number            → string, e.g. "JL 61"
best_flights[].flights[].departure_airport.time   → "YYYY-MM-DD HH:MM"
best_flights[].flights[].arrival_airport.time     → "YYYY-MM-DD HH:MM"
best_flights[].flights[].departure_airport.id     → IATA code, e.g. "BOM"
best_flights[].flights[].arrival_airport.id       → IATA code, e.g. "NRT"
best_flights[].flights[].duration                 → integer, segment duration in minutes
best_flights[].layovers[].duration                → integer, layover duration in minutes
best_flights[].layovers[].name                    → string, layover airport name
best_flights[].layovers[].overnight               → boolean
other_flights[...]                                → same shape; lower-ranked results
```

Stops = `len(best_flights[].flights) - 1` (segments minus one).

### Round-Trip Flow

Round-trip searches require two requests:
1. First request (`type=1`, `outbound_date`, `return_date`) → returns outbound options, each with a `departure_token`
2. Second request with `departure_token` from chosen outbound flight → returns return-leg options

### Rate Limits & Pricing

| Plan | Monthly searches | Cost |
|---|---|---|
| Free | 250 | $0 |
| Developer | 5,000 | $75/month |

Only successful searches count. Cached responses (1-hour TTL) do not count. Error responses do not count.

### Error Codes

| HTTP Status | Meaning | Handling |
|---|---|---|
| 400 | Missing or malformed parameter | Surface config error |
| 401 | Invalid or missing API key | Surface config error |
| 429 | Monthly quota exceeded | Inform user; fall back to web_search for fare estimates |
| 500/503 | SerpApi outage | Return error dict with fallback message |

### Known Limitations

- Prices can occasionally be inaccurate (known SerpApi issue); always label as estimates
- Default results may be fewer than the browser — set `include_hidden_flights=true` for broader results
- `departure_token` for round-trip return legs can sometimes be invalid; handle gracefully with a retry
- No parameter to specify connecting airports (only exclusion via `exclude_conns`)

### Testing Without Live Calls

Store a sample response in `tests/fixtures/serpapi_flights_bom_nrt.json`. Unit tests mock `httpx.get`; the fixture captures the full response shape including `best_flights` and `other_flights`.

---

## Open-Meteo (Weather Forecast)

No API key required. Completely free, no rate-limit enforcement for reasonable use.

### Endpoints Used

#### City Geocoding
```
GET https://geocoding-api.open-meteo.com/v1/search
  ?name=Tokyo
  &count=1
  &language=en
  &format=json
```

Returns: `results[0].latitude`, `results[0].longitude`, `results[0].timezone`

#### Daily Forecast (up to 16 days)
```
GET https://api.open-meteo.com/v1/forecast
  ?latitude=35.6762
  &longitude=139.6503
  &daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode
  &timezone=Asia/Tokyo
  &forecast_days=16
```

#### Historical Climate Averages (trips > 16 days out)
```
GET https://climate-api.open-meteo.com/v1/climate
  ?latitude=35.6762
  &longitude=139.6503
  &start_date=2026-06-01
  &end_date=2026-06-15
  &models=EC_Earth3P_HR
  &daily=temperature_2m_max,temperature_2m_min,precipitation_sum
```

Returns 30-year averages. Label output as "Historical climate average" to avoid misleading users.

### WMO Weather Code Mapping (partial)

| Code | Description |
|---|---|
| 0 | Clear sky |
| 1–3 | Mainly clear / partly cloudy / overcast |
| 45, 48 | Fog |
| 51–55 | Drizzle (light to dense) |
| 61–65 | Rain (slight to heavy) |
| 71–77 | Snow |
| 80–82 | Rain showers |
| 95 | Thunderstorm |
| 96, 99 | Thunderstorm with hail |

Full mapping table implemented in `clients/weather_client.py`.

### Testing Without Live Calls

Open-Meteo is so reliable and fast that integration tests against the live API are fine. For offline unit tests, store sample responses in `tests/fixtures/openmeteo_forecast.json`.

---

## Tavily (Web Search)

### Getting an API Key

1. Sign up at [tavily.com](https://tavily.com)
2. Free tier: 1,000 searches/month

```env
TAVILY_API_KEY=your_tavily_key
```

### Package

```bash
pip install tavily-python
```

### Usage

```python
from tavily import TavilyClient

client = TavilyClient(api_key=api_key)
results = client.search(
    query="Tokyo travel tips 2026 daily budget",
    search_depth="advanced",   # "basic" for quick lookups
    max_results=5,
    include_answer=True        # synthesized answer in addition to results
)
```

### Response Fields

```python
results["answer"]                # synthesized answer string (if include_answer=True)
results["results"][0]["title"]   # page title
results["results"][0]["url"]     # source URL
results["results"][0]["content"] # relevant snippet (clean text, not HTML)
results["results"][0]["score"]   # relevance score 0–1
```

### Queries Run Per Trip

| Query | `search_depth` | Purpose |
|---|---|---|
| `{destination} travel tips {year} budget per day` | `advanced` | Daily cost estimates, tips |
| `visa requirements {destination} {nationality} passport {year}` | `basic` | Visa requirements |
| `{destination} top attractions must see` | `basic` | Activity recommendations |

Track call count in `SearchClient` to stay within the 1,000/month free tier.

### Rate Limits

Free tier: 1,000 searches/month. No per-second rate limit documented; add a 0.5s delay between consecutive calls as a courtesy.

### Error Handling

Wrap all Tavily calls in try/except. On failure, the tool returns `{"status": "error", ...}` and the LLM skips to budget calculation with a note that destination info is unavailable.

### Testing Without Live Calls

Store sample Tavily responses in `tests/fixtures/tavily_tokyo_search.json`. Mock the `TavilyClient.search` method in unit tests.

---

## No API Required: Budget Calculator

The budget calculation step is pure Python — it aggregates outputs from the above tools into a `BudgetBreakdown` model. No external call.

---

## Environment Variable Reference

```env
# LLM (required)
LLM_BASE_URL=https://api.anthropic.com/v1
LLM_API_KEY=sk-ant-...
LLM_MODEL=claude-sonnet-4-6
LLM_EXTRA_HEADERS={"anthropic-version": "2023-06-01"}

# SerpApi (required for flight search)
SERPAPI_API_KEY=...

# Tavily (required for web search)
TAVILY_API_KEY=tvly-...

# Open-Meteo: no key needed
# Frankfurter: no key needed
```

Copy `.env.example` to `.env` and fill in your values.
