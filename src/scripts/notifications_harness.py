import argparse
import os
import sys
import threading

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from config.settings import settings
from config.specialist_tuning import resolve_model_config
from clients.currency_client import CurrencyClient
from clients.llm_client import LLMClient
from clients.search_client import SearchClient
from clients.serpapi_client import SerpApiClient
from clients.weather_client import WeatherClient
from models.knowledge_state import KnowledgeState, UserContext
from notifications import ProgressNotifier
from tools.calculate import CalculateTool
from tools.climate_summary import ClimateSummaryTool
from tools.currency_convert import CurrencyConvertTool
from tools.file_write import FileWriteTool
from tools.flight_search import FlightSearchTool
from tools.get_compiled import GetBudgetCompiledTool, GetCandidatesCompiledTool, GetResearchCompiledTool, GetRouteCompiledTool, GetWeatherCompiledTool
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="What is the weather in Tokyo next week?")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    llm = LLMClient(settings.llm_base_url, settings.llm_api_key, settings.llm_model, resolve_model_config(settings.llm_model).extra_headers)
    progress = ProgressNotifier(LLMClient(settings.llm_base_url, settings.llm_api_key, "qwen3.5:0.8b"))
    q = progress.subscribe()

    def printer() -> None:
        for e in progress.events(q):
            parent = f" parent={e.parent_id}" if e.parent_id else ""
            marker = "○" if e.status == "pending" else "✓"
            print(f"{marker} {e.entry_id}{parent} L{e.level}: {e.label}", flush=True)

    threading.Thread(target=printer, daemon=True).start()

    knowledge = KnowledgeState()
    user_context = UserContext()
    search = SearchClient(settings.tavily_api_key)
    serpapi = SerpApiClient(settings.serpapi_api_key)
    weather_client = WeatherClient()
    currency = CurrencyClient()

    web_search = WebSearchTool(search)
    flight_search = FlightSearchTool(serpapi)
    weather_forecast = WeatherForecastTool(weather_client)
    climate_summary = ClimateSummaryTool(weather_client)
    slice_weather = SliceWeatherRangeTool(knowledge)
    currency_convert = CurrencyConvertTool(currency)
    calculate = CalculateTool()
    get_research = GetResearchCompiledTool(knowledge)
    get_budget = GetBudgetCompiledTool(knowledge)
    get_weather_compiled = GetWeatherCompiledTool(knowledge)
    get_route = GetRouteCompiledTool(knowledge)
    get_candidates = GetCandidatesCompiledTool(knowledge)
    get_itinerary = GetItineraryTool(knowledge)
    self_critique = SelfCritiqueTool(llm)
    file_write = FileWriteTool()

    specialists = {
        "explorer": ExplorerSpecialist(llm, [web_search], debug=args.debug, progress_notifier=progress),
        "weather": WeatherSpecialist(llm, [weather_forecast, climate_summary, slice_weather], knowledge, debug=args.debug, progress_notifier=progress),
        "destination_research": DestinationResearchSpecialist(llm, [web_search], debug=args.debug, progress_notifier=progress),
        "transportation": TransportationSpecialist(llm, [web_search, flight_search], debug=args.debug, progress_notifier=progress),
        "budget": BudgetSpecialist(llm, [web_search, currency_convert, calculate], debug=args.debug, progress_notifier=progress),
        "itinerary_planner": ItineraryPlannerSpecialist(llm, [web_search], debug=args.debug, progress_notifier=progress),
        "artifact": ArtifactSpecialist(llm, [get_research, get_budget, get_weather_compiled, get_route, get_candidates, get_itinerary, self_critique, file_write], debug=args.debug, progress_notifier=progress),
    }
    orchestrator = Orchestrator(llm, user_context, knowledge, specialists, debug=args.debug, progress_notifier=progress)
    print(orchestrator.turn(args.query))


if __name__ == "__main__":
    main()
