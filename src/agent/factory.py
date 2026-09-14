from functools import cache

import nltk

from agent.orchestrator import Orchestrator
from clients.currency_client import CurrencyClient
from clients.llm_client import LLMClient
from clients.search_client import SearchClient
from clients.serpapi_client import SerpApiClient
from clients.weather_client import WeatherClient
from config.settings import settings
from config.specialist_tuning import resolve_model_config
from models.knowledge_state import KnowledgeState, UserContext
from notifications import ProgressNotifier
from specialists.artifact import ArtifactSpecialist
from specialists.budget import BudgetSpecialist
from specialists.destination_research import DestinationResearchSpecialist
from specialists.explorer import ExplorerSpecialist
from specialists.itinerary_planner import ItineraryPlannerSpecialist
from specialists.transportation import TransportationSpecialist
from specialists.weather import WeatherSpecialist
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


def configure_progress_notifier(progress: ProgressNotifier) -> None:
    progress.set_llm(LLMClient(
        settings.progress_llm_base_url,
        settings.progress_llm_api_key,
        settings.progress_llm_model,
    ))


def create_progress_notifier() -> ProgressNotifier:
    progress = ProgressNotifier()
    configure_progress_notifier(progress)
    return progress


@cache
def ensure_nltk_data() -> None:
    for resource in ("stopwords", "wordnet", "punkt_tab"):
        nltk.download(resource, quiet=True)


def build_orchestrator(*, progress: ProgressNotifier, file_write: FileWriteTool | None = None, debug: bool = False) -> Orchestrator:
    ensure_nltk_data()

    llm_client = LLMClient(
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
        extra_headers=resolve_model_config(settings.llm_model).extra_headers,
    )
    knowledge = KnowledgeState()
    user_context = UserContext()
    web_search = WebSearchTool(SearchClient(settings.tavily_api_key))
    weather_client = WeatherClient()
    currency_client = CurrencyClient()
    specialists = {
        "explorer": ExplorerSpecialist(llm_client, [web_search], debug=debug, progress_notifier=progress),
        "weather": WeatherSpecialist(llm_client, [WeatherForecastTool(weather_client), ClimateSummaryTool(weather_client), SliceWeatherRangeTool(knowledge)], knowledge, debug=debug, progress_notifier=progress),
        "destination_research": DestinationResearchSpecialist(llm_client, [web_search], debug=debug, progress_notifier=progress),
        "transportation": TransportationSpecialist(llm_client, [web_search, FlightSearchTool(SerpApiClient(settings.serpapi_api_key))], debug=debug, progress_notifier=progress),
        "budget": BudgetSpecialist(llm_client, [web_search, CurrencyConvertTool(currency_client), CalculateTool()], debug=debug, progress_notifier=progress),
        "itinerary_planner": ItineraryPlannerSpecialist(llm_client, [web_search], debug=debug, progress_notifier=progress),
        "artifact": ArtifactSpecialist(
            llm_client,
            [GetResearchCompiledTool(knowledge), GetBudgetCompiledTool(knowledge), GetWeatherCompiledTool(knowledge), GetRouteCompiledTool(knowledge), GetCandidatesCompiledTool(knowledge), GetItineraryTool(knowledge), SelfCritiqueTool(llm_client), file_write or FileWriteTool()],
            debug=debug,
            progress_notifier=progress,
        ),
    }
    return Orchestrator(llm_client, user_context, knowledge, specialists, debug=debug, progress_notifier=progress)
