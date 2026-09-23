from models.knowledge_state import KnowledgeState
from tools.base import BaseTool
from tools.itinerary_planner_wrapper import render_itinerary


class GetItineraryTool(BaseTool):
    name = "get_itinerary"
    description = (
        "Fetch the saved itinerary from KnowledgeState. The `destinations` values must be copied "
        "character-for-character from the backtick-quoted ITINERARIES or DESTINATIONS keys; "
        "do not shorten or normalize them. Returns a full day-by-day itinerary with all slots "
        "including weather-contingency alternatives."
    )
    parameters = {
        "type": "object",
        "properties": {
            "destinations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of exact backtick-quoted ITINERARIES/DESTINATIONS keys, copied verbatim.",
            },
        },
        "required": ["destinations"],
    }

    def __init__(self, knowledge: KnowledgeState):
        self._knowledge = knowledge

    def execute(self, **kwargs) -> dict:
        destinations: list[str] = kwargs["destinations"]
        key = frozenset(destinations)
        itinerary = self._knowledge.itineraries.get(key)
        if itinerary is None:
            return {"result": f"No itinerary found for {', '.join(destinations)}. Call itinerary_planner first."}
        itinerary.stale = False
        return {"result": render_itinerary(itinerary)}
