from models.knowledge_state import KnowledgeState, DateRange
from models.weather import WeatherOutput
from specialists.weather import WeatherSpecialist
from tools.base import BaseTool


class WeatherWrapperTool(BaseTool):
    name = "weather"
    description = (
        "Get weather forecast or historical climate summary for a destination and date range."
    )
    parameters = {
        "type": "object",
        "properties": {
            "destination": {
                "type": "string",
                "description": "City-level — a specific geocodable city, not a region or country.",
            },
            "date_range": {
                "type": "string",
                "description": (
                    "Plain string describing the travel dates. "
                    "Examples: '2026-06-20 to 2026-06-30', 'late June 2026', 'next few months'. "
                    "Specific ISO ranges trigger forecast mode (≤16 days out) or climate mode; "
                    "vague strings always use climate mode."
                ),
            },
        },
        "required": ["destination", "date_range"],
    }

    def __init__(self, specialist: WeatherSpecialist, knowledge: KnowledgeState):
        self._specialist = specialist
        self._knowledge = knowledge

    def execute(self, **kwargs) -> dict:
        destination: str = kwargs["destination"]
        date_range_str: str = kwargs["date_range"]
        date_range = DateRange.from_string(date_range_str)
        ks = self._knowledge

        # Pre-firing check: exact key hit → return cached summary without calling specialist
        dk = ks.destinations.get(destination)
        if dk and date_range in dk.weather:
            return {
                "status": "ok",
                "summary": self._template_summary(destination, date_range_str, dk.weather[date_range]),
                "from_cache": True,
            }

        # Cache miss — pass existing entries with actual date coverage so the
        # specialist can detect subset/augment opportunities before making API calls.
        # The label may be a vague string ("late June 2026"); the actual coverage
        # from wo.days[0].date / wo.days[-1].date is what enables overlap reasoning.
        existing: dict[str, str] = {}
        if dk and dk.weather:
            for dr, wo in dk.weather.items():
                if wo.days:
                    coverage = f"{wo.days[0].date} to {wo.days[-1].date}"
                    existing[dr.label] = f"{wo.mode}, {len(wo.days)} days, covers {coverage}"
                else:
                    existing[dr.label] = f"{wo.mode}, 0 days"

        try:
            self._specialist.run(
                destination=destination,
                date_range=date_range_str,
                existing_entries=existing if existing else None,
            )
        except Exception as e:
            return {"status": "error", "summary": f"WeatherSpecialist failed: {e}"}

        # Read result that the specialist wrote to KnowledgeState
        dk = ks.destinations.get(destination)
        if not dk or date_range not in dk.weather:
            return {"status": "error", "summary": f"WeatherSpecialist ran but no data found for {destination} {date_range_str}"}

        return {
            "status": "ok",
            "summary": self._template_summary(destination, date_range_str, dk.weather[date_range]),
        }

    @staticmethod
    def _template_summary(destination: str, date_range: str, wo: WeatherOutput) -> str:
        if not wo.days:
            return f"{destination} {date_range}: no data available"

        avg_high = sum(d.temp_max for d in wo.days) / len(wo.days)
        avg_low = sum(d.temp_min for d in wo.days) / len(wo.days)

        if wo.mode == "forecast":
            probs = [d.precipitation_prob for d in wo.days if d.precipitation_prob is not None]
            avg_precip = sum(probs) / len(probs) if probs else 0
            return (
                f"{destination} {date_range}: "
                f"avg high {avg_high:.0f}°C / low {avg_low:.0f}°C, "
                f"{avg_precip:.0f}% precip."
            )
        else:
            sums = [d.precipitation_sum for d in wo.days if d.precipitation_sum is not None]
            avg_sum = sum(sums) / len(sums) if sums else 0
            return (
                f"{destination} {date_range} (historical avg): "
                f"avg high {avg_high:.0f}°C / low {avg_low:.0f}°C, "
                f"~{avg_sum:.1f}mm/day precip."
            )
