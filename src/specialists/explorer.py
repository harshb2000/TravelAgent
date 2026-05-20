from models.knowledge_state import DestinationCandidate, KnowledgeState, UserContext
from clients.llm_client import LLMClient
from tools.base import BaseTool


EXPLORER_CACHE_THRESHOLD = 0.6


class ExplorerSpecialist:
    def __init__(self, llm_client: LLMClient, tools: list[BaseTool]):
        self._llm = llm_client
        self._tools = tools

    def run(
        self,
        query: str,
        max_results: int = 5,
        existing_candidates: list[DestinationCandidate] | None = None,
    ) -> list[DestinationCandidate]:
        return []
