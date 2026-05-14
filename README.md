# TravelAgent

An agentic travel planner chatbot that helps you plan a trip from scratch — flight options, weather forecasts, destination research, budget breakdown, and a day-by-day itinerary — through a natural language conversation.

Built with a hand-rolled agentic loop (no SDK frameworks) so the LLM backend is fully swappable: Anthropic, Groq, Together.ai, Ollama, or any OpenAI-compatible endpoint.

## Features (MVP v1)

- **Conversational intent extraction** — describe your trip in plain language
- **Flight search** — real options via Google Flights (SerpApi): one-way, round-trip, multi-city
- **Weather forecast** — daily highs/lows and precipitation via Open-Meteo
- **Destination research** — things to do, daily costs, visa info via Tavily web search
- **Budget breakdown** — flights + accommodation estimate + daily expenses vs. your budget
- **Itinerary generation** — day-by-day plan saved as a Markdown file

See [`docs/v1/features.md`](docs/v1/features.md) for the full feature spec.

## Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/harshb2000/TravelAgent.git
cd TravelAgent
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r src/requirements.txt
```

### 2. Configure environment variables

```bash
cp src/.env.example src/.env
# Edit src/.env with your API keys (see docs/v1/api_integrations.md for how to get each key)
```

Required keys:
```
LLM_BASE_URL=https://api.anthropic.com/v1          # or any OpenAI-compatible endpoint
LLM_API_KEY=your_key_here
LLM_MODEL=claude-sonnet-4-6                        # or llama3, mistral, etc.
LLM_EXTRA_HEADERS={"anthropic-version": "2023-06-01"}
SERPAPI_API_KEY=your_serpapi_key
TAVILY_API_KEY=your_tavily_key
```

### 3. Run

```bash
python src/main.py
```

## Documentation

| Doc | Description |
|---|---|
| [`docs/v1/features.md`](docs/v1/features.md) | Full feature spec |
| [`docs/v1/architecture.md`](docs/v1/architecture.md) | Agent loop design, module structure, data flow |
| [`docs/v1/philosophy.md`](docs/v1/philosophy.md) | Design principles and reasoning |
| [`docs/v1/api_integrations.md`](docs/v1/api_integrations.md) | API setup, endpoints, rate limits, error handling |
| [`docs/v1/implementation_plan.md`](docs/v1/implementation_plan.md) | Phased build plan with progress |

## Tech Stack

- Python 3.13
- Raw `httpx` HTTP calls to any OpenAI-compatible LLM endpoint
- SerpApi Google Flights (flight search)
- Open-Meteo (weather, no key required)
- Tavily (web search)
- Frankfurter (currency conversion, no key required)
- Pydantic, Rich, python-dotenv
