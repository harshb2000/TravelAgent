from tools.base import BaseTool
from models.knowledge_state import KnowledgeState


class SliceWeatherRangeTool(BaseTool):
    name = "slice_weather_range"
    description = (
        "Extract a date-range subset from an existing weather entry in KnowledgeState. "
        "Use for two cases:\n"
        "  Subset: requested range is fully contained within an existing entry — "
        "call alone in a single iteration with start_date/end_date to bound the slice.\n"
        "  Augment: requested range extends an existing entry — call this in parallel "
        "with weather_forecast or climate_summary (each covering its portion) in one iteration; "
        "the wrapper merges the results."
    )
    parameters = {
        "type": "object",
        "properties": {
            "destination": {
                "type": "string",
                "description": "City name exactly as stored in KnowledgeState.",
            },
            "source_range": {
                "type": "string",
                "description": "Label of the existing DateRange entry to slice from "
                               "(e.g. '2026-06-01 to 2026-06-30').",
            },
            "start_date": {
                "type": "string",
                "description": "YYYY-MM-DD — start of the desired slice, inclusive. "
                               "Omit to keep from the beginning of the source range.",
            },
            "end_date": {
                "type": "string",
                "description": "YYYY-MM-DD — end of the desired slice, inclusive. "
                               "Omit to keep to the end of the source range.",
            },
        },
        "required": ["destination", "source_range"],
    }

    def __init__(self, knowledge_state: KnowledgeState):
        self._knowledge = knowledge_state

    def execute(self, **kwargs) -> dict:
        destination: str = kwargs["destination"]
        source_label: str = kwargs["source_range"]
        start_date: str | None = kwargs.get("start_date")
        end_date: str | None = kwargs.get("end_date")

        dk = self._knowledge.destinations.get(destination)
        if not dk:
            return {"status": "error", "error": f"No weather data for '{destination}'", "fallback": ""}

        existing_wo = None
        for dr, wo in dk.weather.items():
            if dr.label == source_label:
                existing_wo = wo
                break

        if not existing_wo:
            return {
                "status": "error",
                "error": f"No weather entry with label '{source_label}' for {destination}",
                "fallback": "",
            }

        days = existing_wo.days
        if start_date:
            days = [d for d in days if d.date >= start_date]
        if end_date:
            days = [d for d in days if d.date <= end_date]

        return {
            "status": "ok",
            "mode": existing_wo.mode,
            "city": existing_wo.city,
            "days": [d.model_dump() for d in days],
        }
