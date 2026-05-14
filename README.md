# TravelAgent

An agentic travel planner chatbot that helps you plan a trip from scratch — flight options, weather forecasts, destination research, budget breakdown, and a day-by-day itinerary — through a natural language conversation.

Built with a hand-rolled agentic loop (no SDK frameworks) so the LLM backend is fully swappable: Anthropic, Groq, Together.ai, Ollama, or any OpenAI-compatible endpoint.

## Features (MVP v1)

- **Conversational intent extraction** — describe your trip in plain language
- **Flight search** — real options via Amadeus API (airline, price, stops, duration)
- **Weather forecast** — daily highs/lows and precipitation via Open-Meteo
- **Destination research** — things to do, daily costs, visa info via Tavily web search
- **Budget breakdown** — flights + accommodation estimate + daily expenses vs. your budget
- **Itinerary generation** — day-by-day plan saved as a Markdown file

See [`docs/MVP_features_v1.md`](docs/MVP_features_v1.md) for the full feature spec.

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <repo>
cd TravelAgent
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your API keys (see docs/api_integrations.md for how to get each key)
```

Required keys:
```
LLM_BASE_URL=https://api.anthropic.com/v1          # or any OpenAI-compatible endpoint
LLM_API_KEY=your_key_here
LLM_MODEL=claude-sonnet-4-6                        # or llama3, mistral, etc.
AMADEUS_CLIENT_ID=your_amadeus_client_id
AMADEUS_CLIENT_SECRET=your_amadeus_client_secret
TAVILY_API_KEY=your_tavily_key
```

### 3. Run

```bash
python main.py
```

## Documentation

| Doc | Description |
|---|---|
| [`docs/MVP_features_v1.md`](docs/MVP_features_v1.md) | Full feature spec: user stories, acceptance criteria, out-of-scope |
| [`docs/architecture.md`](docs/architecture.md) | Agent loop design, module structure, data flow |
| [`docs/api_integrations.md`](docs/api_integrations.md) | API setup, endpoints, rate limits, error handling |
| [`docs/implementation_plan.md`](docs/implementation_plan.md) | Phased build plan |
| [`docs/roadmap.md`](docs/roadmap.md) | v1 → v2 → v3 feature progression |

## Tech Stack

- Python 3.13
- Raw `httpx` HTTP calls to any OpenAI-compatible LLM endpoint
- Amadeus Self-Service API (flights)
- Open-Meteo (weather, no key required)
- Tavily (web search)
- Pydantic, Rich, python-dotenv
