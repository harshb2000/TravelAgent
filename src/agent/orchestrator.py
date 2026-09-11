from datetime import date

from agent.harness import SimpleReActAgent
from agent.prompts.orchestrator import ORCHESTRATOR_PROMPT
from clients.llm_client import LLMClient
from config.specialist_tuning import resolve_tuning
from models.knowledge_state import KnowledgeState, UserContext
from notifications import ProgressNotifier
from tools.artifact_wrapper import ArtifactWrapperTool
from tools.budget_wrapper import BudgetWrapperTool
from tools.destination_research_wrapper import DestinationResearchWrapperTool
from tools.explorer_wrapper import ExplorerWrapperTool
from tools.itinerary_planner_wrapper import ItineraryPlannerWrapperTool
from tools.transportation_wrapper import TransportationWrapperTool
from tools.update_user_context import UpdateUserContextTool
from tools.weather_wrapper import WeatherWrapperTool


class Orchestrator:
    def __init__(
        self,
        llm_client: LLMClient,
        user_context: UserContext,
        knowledge: KnowledgeState,
        specialists: dict,
        debug: bool = False,
        progress_notifier: ProgressNotifier | None = None,
    ):
        self._user_context = user_context
        self._knowledge = knowledge
        tuning = resolve_tuning("orchestrator", llm_client.model)

        wrapper_tools = [
            ExplorerWrapperTool(specialists["explorer"], knowledge, user_context),
            WeatherWrapperTool(specialists["weather"], knowledge),
            DestinationResearchWrapperTool(specialists["destination_research"], knowledge, user_context),
            TransportationWrapperTool(specialists["transportation"], knowledge, user_context),
            BudgetWrapperTool(specialists["budget"], knowledge, user_context),
            ItineraryPlannerWrapperTool(specialists["itinerary_planner"], knowledge, user_context),
            ArtifactWrapperTool(specialists["artifact"], knowledge, user_context),
            UpdateUserContextTool(user_context),
        ]

        self._agent = SimpleReActAgent(
            llm_client, wrapper_tools, ORCHESTRATOR_PROMPT, max_iterations=tuning.max_iterations, debug=debug,
            extra_body=tuning.extra_body, timeout=tuning.timeout_s,
            progress_notifier=progress_notifier,
        )

    def turn(self, user_input: str) -> str:
        task = (
            f"Today: {date.today().isoformat()}\n"
            f"UserContext:\n{self._user_context.context}\n\n"
            f"KnowledgeState:\n{self._knowledge.to_prompt_context(self._user_context)}\n\n"
            f"User message: {user_input}"
        )
        return self._agent.run(task)
