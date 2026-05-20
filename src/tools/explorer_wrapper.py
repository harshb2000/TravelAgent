from tools.base import BaseTool
from models.knowledge_state import KnowledgeState, UserContext


class ExplorerWrapperTool(BaseTool):
    name = "explorer"
    description = "Discover destination candidates that match the user's travel intent."
    parameters = {
        "type": "object",
        "properties": {
            "query":       {"type": "string", "description": "Exploration query"},
            "max_results": {"type": "integer", "description": "Max candidates to return (default 5)"},
        },
        "required": ["query"],
    }

    def __init__(self, specialist, knowledge: KnowledgeState, user_context: UserContext):
        self._specialist = specialist
        self._knowledge = knowledge
        self._user_context = user_context

    def execute(self, **kwargs) -> dict:
        return {"status": "stub", "summary": ""}
