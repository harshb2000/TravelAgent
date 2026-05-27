import argparse
import sys

import nltk
from rich.console import Console
from rich.markdown import Markdown

from config.settings import settings
from clients.currency_client import CurrencyClient
from clients.llm_client import LLMClient
from clients.search_client import SearchClient
from clients.serpapi_client import SerpApiClient
from clients.weather_client import WeatherClient
from models.knowledge_state import KnowledgeState, UserContext
from tools.calculate import CalculateTool
from tools.climate_summary import ClimateSummaryTool
from tools.currency_convert import CurrencyConvertTool
from tools.file_write import FileWriteTool
from tools.flight_search import FlightSearchTool
from tools.get_compiled import (
    GetBudgetCompiledTool,
    GetCandidatesCompiledTool,
    GetResearchCompiledTool,
    GetRouteCompiledTool,
    GetWeatherCompiledTool,
)
from tools.get_itinerary import GetItineraryTool
from tools.self_critique import SelfCritiqueTool
from tools.slice_weather_range import SliceWeatherRangeTool
from tools.weather_forecast import WeatherForecastTool
from tools.web_search import WebSearchTool
from specialists.artifact import ArtifactSpecialist
from specialists.budget import BudgetSpecialist
from specialists.destination_research import DestinationResearchSpecialist
from specialists.explorer import ExplorerSpecialist
from specialists.itinerary_planner import ItineraryPlannerSpecialist
from specialists.transportation import TransportationSpecialist
from specialists.weather import WeatherSpecialist
from agent.orchestrator import Orchestrator


def ensure_nltk_data() -> None:
    for resource in ("stopwords", "wordnet", "punkt_tab"):
        nltk.download(resource, quiet=True)


def validate_settings() -> None:
    missing = [
        name for name, val in [
            ("LLM_BASE_URL", settings.llm_base_url),
            ("LLM_API_KEY", settings.llm_api_key),
            ("LLM_MODEL", settings.llm_model),
        ] if not val
    ]
    if missing:
        print(f"Error: missing required env vars: {', '.join(missing)}", file=sys.stderr)
        print("Copy .env.example to .env and fill in the values.", file=sys.stderr)
        sys.exit(1)
    if not settings.serpapi_api_key:
        print("Warning: SERPAPI_API_KEY not set — flight search unavailable.", file=sys.stderr)
    if not settings.tavily_api_key:
        print("Warning: TAVILY_API_KEY not set — web search unavailable.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="TravelAgent CLI")
    parser.add_argument("--debug", action="store_true", help="Print tool calls and results to stderr")
    args = parser.parse_args()

    ensure_nltk_data()
    validate_settings()

    console = Console()

    # Clients
    llm_client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        extra_headers=settings.llm_extra_headers,
    )
    serpapi_client = SerpApiClient(settings.serpapi_api_key)
    weather_client = WeatherClient()
    currency_client = CurrencyClient()
    search_client = SearchClient(settings.tavily_api_key)

    # Session state
    knowledge = KnowledgeState()
    user_context = UserContext()

    # Shared tools
    web_search = WebSearchTool(search_client)
    flight_search = FlightSearchTool(serpapi_client)
    weather_forecast = WeatherForecastTool(weather_client)
    climate_summary = ClimateSummaryTool(weather_client)
    currency_convert = CurrencyConvertTool(currency_client)
    calculate = CalculateTool()
    file_write = FileWriteTool()

    # KnowledgeState-aware tools
    slice_weather = SliceWeatherRangeTool(knowledge)
    get_research = GetResearchCompiledTool(knowledge)
    get_budget = GetBudgetCompiledTool(knowledge)
    get_weather_compiled = GetWeatherCompiledTool(knowledge)
    get_route = GetRouteCompiledTool(knowledge)
    get_candidates = GetCandidatesCompiledTool(knowledge)
    get_itinerary = GetItineraryTool(knowledge)
    self_critique = SelfCritiqueTool(llm_client)

    # Specialists
    specialists = {
        "explorer": ExplorerSpecialist(llm_client, [web_search], debug=args.debug),
        "weather": WeatherSpecialist(llm_client, [weather_forecast, climate_summary, slice_weather], knowledge),
        "destination_research": DestinationResearchSpecialist(llm_client, [web_search], debug=args.debug),
        "transportation": TransportationSpecialist(llm_client, [web_search, flight_search], debug=args.debug),
        "budget": BudgetSpecialist(llm_client, [web_search, currency_convert, calculate], debug=args.debug),
        "itinerary_planner": ItineraryPlannerSpecialist(llm_client, [web_search], debug=args.debug),
        "artifact": ArtifactSpecialist(
            llm_client,
            [get_research, get_budget, get_weather_compiled, get_route, get_candidates,
             get_itinerary, self_critique, file_write],
            debug=args.debug,
        ),
    }

    orchestrator = Orchestrator(llm_client, user_context, knowledge, specialists, debug=args.debug)

    console.print("[bold]TravelAgent[/bold] — type your message, Ctrl-C to quit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\nGoodbye.")
            break
        if not user_input:
            continue

        try:
            with console.status("[dim]Thinking…[/dim]"):
                response = orchestrator.turn(user_input)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            continue

        console.print()
        console.print(Markdown(response))
        console.print()


if __name__ == "__main__":
    main()
