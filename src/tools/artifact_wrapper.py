import datetime

from models.knowledge_state import KnowledgeState, UserContext
from specialists.artifact import ArtifactSpecialist
from tools.base import BaseTool

_FOOTER_TEMPLATE = """
---
Generated: {date}
Flights: Google Flights via SerpApi · Weather: Open-Meteo · Research & costs: Tavily web search
Pricing is estimated — verify before booking.
"""


def _append_footer(file_path: str) -> None:
    footer = _FOOTER_TEMPLATE.format(date=datetime.date.today().isoformat())
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(footer)
    except OSError:
        pass


class ArtifactWrapperTool(BaseTool):
    name = "artifact"
    description = (
        "Generate and save a comprehensive travel document to disk. "
        "Compiles all available KnowledgeState data — research, budget, weather, routes, itinerary — "
        "into a well-sourced Markdown file. Call when the user explicitly requests a saved document."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The user's artifact request verbatim.",
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        specialist: ArtifactSpecialist,
        knowledge: KnowledgeState,
        user_context: UserContext,
    ):
        self._specialist = specialist
        self._knowledge = knowledge
        self._user_context = user_context

    def execute(self, **kwargs) -> dict:
        query: str = kwargs["query"]
        context = self._knowledge.to_prompt_context(self._user_context)

        try:
            result = self._specialist.run(query, context)
        except Exception as e:
            return {"status": "error", "summary": f"ArtifactSpecialist failed: {e}"}

        if result.missing_data:
            gaps = "\n".join(f"- {item}" for item in result.missing_data)
            return {
                "status": "needs_data",
                "summary": (
                    f"Cannot generate artifact — missing required data:\n{gaps}\n"
                    "Gather this data first, then call artifact again."
                ),
            }

        _append_footer(result.file_path)
        return {"status": "ok", "summary": f"Artifact saved to: {result.file_path}"}
