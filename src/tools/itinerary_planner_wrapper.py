from agent.prompts.itinerary_planner import PRECIP_PROB_THRESHOLD, PRECIP_SUM_THRESHOLD
from models.knowledge_state import Itinerary, KnowledgeState, UserContext
from specialists.itinerary_planner import ItineraryPlannerSpecialist
from tools.base import BaseTool


class ItineraryPlannerWrapperTool(BaseTool):
    name = "itinerary_planner"
    description = (
        "Build or refine a day-by-day itinerary for one or more destinations. "
        "Requires full-depth destination research and weather data to be present. "
        "Automatically incorporates weather-aware scheduling and activity enrichment. "
        "Call when approximate dates and destination research (full depth) are both available and the "
        "user asks for a day-by-day plan."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Free-form trip intent and structure, e.g. "
                    "'10 days Tokyo + 3 days Kyoto, June 20 arrival. "
                    "User prefers cultural and food experiences, mid-pace.'"
                ),
            },
            "destinations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered list of destination city names for this itinerary.",
            },
        },
        "required": ["query", "destinations"],
    }

    def __init__(
        self,
        specialist: ItineraryPlannerSpecialist,
        knowledge: KnowledgeState,
        user_context: UserContext,
    ):
        self._specialist = specialist
        self._knowledge = knowledge
        self._user_context = user_context

    def execute(self, **kwargs) -> dict:
        query: str = kwargs["query"]
        destinations: list[str] = kwargs["destinations"]

        missing = _missing_full_research(destinations, self._knowledge)
        if missing:
            return {
                "status": "error",
                "summary": (
                    f"ItineraryPlannerSpecialist requires full-depth research for all destinations. "
                    f"Missing or incomplete: {', '.join(missing)}. "
                    f"Call DestinationResearchSpecialist with depth='full' for each first."
                ),
            }

        context = _build_context(destinations, self._user_context.context, self._knowledge)

        try:
            result = self._specialist.run(query, context)
        except Exception as e:
            return {"status": "error", "summary": f"ItineraryPlannerSpecialist failed: {e}"}

        if not result.itinerary.days:
            try:
                result = self._specialist.run(
                    "The itinerary you returned had no days. "
                    "Please generate a complete day-by-day itinerary with all days filled in."
                )
            except Exception as e:
                return {"status": "error", "summary": f"ItineraryPlannerSpecialist failed on retry: {e}"}

            if not result.itinerary.days:
                return {
                    "status": "error",
                    "summary": (
                        f"ItineraryPlannerSpecialist returned an empty itinerary for "
                        f"{', '.join(destinations)} after two attempts."
                    ),
                }

        self._knowledge.update_itinerary(frozenset(destinations), result.itinerary)

        for destination, activities in result.activity_updates.items():
            if activities:
                self._knowledge.update_activities(destination, activities)

        return {"status": "ok", "summary": render_itinerary(result.itinerary)}


def _missing_full_research(destinations: list[str], knowledge: KnowledgeState) -> list[str]:
    """Return destinations that lack full-depth DestinationResearch."""
    missing = []
    for destination in destinations:
        dk = knowledge.destinations.get(destination)
        if not dk or not dk.research or dk.research.depth != "full":
            missing.append(destination)
    return missing


def _build_context(
    destinations: list[str],
    user_context: str,
    knowledge: KnowledgeState,
) -> str:
    lines: list[str] = []

    if user_context:
        lines.append(f"UserContext: {user_context}")

    for destination in destinations:
        dk = knowledge.destinations.get(destination)
        if not dk:
            continue

        if dk.research:
            r = dk.research
            lines.append(f"\nDestinationResearch for {destination}:")
            lines.append(f"  depth: {r.depth}")
            lines.append(f"  vibe: {r.vibe}")
            if r.top_attractions:
                lines.append(f"  top_attractions: {', '.join(r.top_attractions)}")
            if r.summary:
                lines.append(f"  summary: {r.summary}")
            if r.festivals:
                lines.append(f"  festivals: {', '.join(r.festivals)}")
            if r.notable_areas:
                lines.append("  notable_areas:")
                for name, na in r.notable_areas.items():
                    highlights = ", ".join(na.highlights) if na.highlights else "—"
                    lines.append(f"    {name}: {na.description} | highlights: {highlights}")
            if r.activities:
                lines.append("  activities:")
                for act in r.activities:
                    tags = ", ".join(act.tags) if act.tags else "—"
                    indoor = "indoor" if act.indoor else "outdoor"
                    dur = f"{act.duration_min}min" if act.duration_min else "duration unknown"
                    lines.append(f"    {act.name} [{tags}] ({indoor}, {dur})")

        if dk.weather:
            lines.append(f"\nWeather for {destination}:")
            for dr, wo in dk.weather.items():
                if not wo.days:
                    continue
                avg_high = sum(d.temp_max for d in wo.days) / len(wo.days)
                avg_low = sum(d.temp_min for d in wo.days) / len(wo.days)
                mode_label = "forecast" if wo.mode == "forecast" else "historical avg"
                lines.append(
                    f"  {dr.label} ({mode_label}): "
                    f"avg high {avg_high:.0f}°C / low {avg_low:.0f}°C"
                )
                rainy = [
                    d.date for d in wo.days
                    if (d.precipitation_prob is not None and d.precipitation_prob > PRECIP_PROB_THRESHOLD)
                    or (d.precipitation_sum is not None and d.precipitation_sum > PRECIP_SUM_THRESHOLD)
                ]
                if rainy:
                    lines.append(f"    high-precip days: {', '.join(rainy)}")

    return "\n".join(lines)


def render_itinerary(itinerary: Itinerary) -> str:
    destinations_str = " + ".join(itinerary.destinations) if itinerary.destinations else "unknown"
    n_days = len(itinerary.days)
    start = itinerary.start_date or "dates TBD"

    lines = [f"{n_days}-day itinerary for {destinations_str} ({start}):"]

    for day in itinerary.days:
        label_parts = []
        if day.is_arrival:
            label_parts.append("Arrival")
        if day.is_departure:
            label_parts.append("Departure")
        if day.is_transit:
            label_parts.append("Transit")

        header = f"\nDay {day.day_num} ({day.location})"
        if label_parts:
            header += f" [{', '.join(label_parts)}]"
        if day.weather_note:
            header += f" — {day.weather_note}"
        lines.append(header + ":")

        for slot in day.slots:
            alt_marker = " [alt]" if slot.is_alternative else ""
            tags = ", ".join(slot.activity.tags) if slot.activity.tags else ""
            tag_str = f" [{tags}]" if tags else ""
            indoor = "indoor" if slot.activity.indoor else "outdoor"
            dur = f", {slot.activity.duration_min}min" if slot.activity.duration_min else ""
            src = f" [source]({slot.activity.source_url})" if slot.activity.source_url else ""
            loc = f" @ {slot.location}" if slot.location else ""
            notes = f" — {slot.notes}" if slot.notes else ""
            lines.append(
                f"  {slot.start_time}{alt_marker} | {slot.activity.name}{tag_str}"
                f" ({indoor}{dur}){src}{loc}{notes}"
            )

    if itinerary.notes:
        lines.append(f"\nNotes: {itinerary.notes}")

    return "\n".join(lines)
