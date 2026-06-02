from tools.base import BaseTool
from models.knowledge_state import KnowledgeState, UserContext
from specialists.destination_research import DestinationResearchSpecialist


class DestinationResearchWrapperTool(BaseTool):
    name = "destination_research"
    description = (
        "Research a destination — vibe, attractions, safety, visa requirements, "
        "notable areas, and activities."
    )
    parameters = {
        "type": "object",
        "properties": {
            "destination": {
                "type": "string",
                "description": "Entity-level name — a region, island, or named area as the user thinks of it (e.g. 'Sikkim', 'Bali', 'Kyoto').",
            },
            "depth": {
                "type": "string",
                "enum": ["light", "full"],
                "description": (
                    "'light': vibe + top attractions only — sufficient for shortlisting. "
                    "'full': complete research including safety, visa, notable areas, activities."
                ),
            },
        },
        "required": ["destination", "depth"],
    }

    def __init__(
        self,
        specialist: DestinationResearchSpecialist,
        knowledge: KnowledgeState,
        user_context: UserContext,
    ):
        self._specialist = specialist
        self._knowledge = knowledge
        self._user_context = user_context

    def execute(self, **kwargs) -> dict:
        destination: str = kwargs["destination"]
        depth: str = kwargs.get("depth", "light")
        user_context: str = self._user_context.context
        ks = self._knowledge

        # Pre-firing check — five-case table from architecture.md
        existing = ks.destinations.get(destination)
        existing_research = existing.research if existing else None

        if existing_research is not None:
            existing_depth = existing_research.depth
            # Cache hits: light→light, full→light (full is superset)
            if depth == "light":
                return {"status": "ok", "summary": existing_research.summary}
            # depth == "full" from here
            if existing_depth == "light":
                max_iterations = 3   # upgrade: light → full
            else:
                max_iterations = 4   # pass-through: full → full (specialist self-directs)
        else:
            max_iterations = 1 if depth == "light" else 4   # full miss

        try:
            result = self._specialist.run(destination, depth, user_context, max_iterations, existing_research)
        except Exception as e:
            return {"status": "error", "summary": f"DestinationResearchSpecialist failed: {e}"}

        ks.update_research(destination, result)
        return {"status": "ok", "summary": result.summary}
