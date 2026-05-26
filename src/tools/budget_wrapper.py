from models.knowledge_state import KnowledgeState, DateRange, UserContext
from specialists.budget import BudgetSpecialist
from tools.base import BaseTool


class BudgetWrapperTool(BaseTool):
    name = "budget"
    description = (
        "Calculate a detailed trip budget including flights, accommodation, food, "
        "local transport, and activities. Returns a formatted cost breakdown with "
        "totals in USD and home currency. Call when the user asks about costs, "
        "budget feasibility, or destination cost comparisons."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Free-form trip configuration string, e.g. "
                    "'2 people, 7 nights Tokyo late June, flying Mumbai round-trip, "
                    "mid-range hotel, budget ₹2.5L/person'."
                ),
            },
            "destination": {
                "type": "string",
                "description": "Primary destination city name for KnowledgeState lookup and update.",
            },
        },
        "required": ["query", "destination"],
    }

    def __init__(
        self,
        specialist: BudgetSpecialist,
        knowledge: KnowledgeState,
        user_context: UserContext,
    ):
        self._specialist = specialist
        self._knowledge = knowledge
        self._user_context = user_context

    def execute(self, **kwargs) -> dict:
        query: str = kwargs["query"]
        destination: str = kwargs["destination"]

        context = _build_context(destination, self._user_context.context, self._knowledge)

        try:
            result = self._specialist.run(query, context)
        except Exception as e:
            return {"status": "error", "summary": f"BudgetSpecialist failed: {e}"}

        if result.destination_budget is not None:
            self._knowledge.update_destination_budget(destination, result.destination_budget)

        return {"status": "ok", "summary": result.breakdown}


def _build_context(
    destination: str,
    user_context: str,
    knowledge: KnowledgeState,
) -> str:
    lines: list[str] = []

    if user_context:
        lines.append(f"UserContext: {user_context}")

    dk = knowledge.destinations.get(destination)
    if dk and dk.budget:
        budget = dk.budget
        lines.append(f"\nExisting budget data for {destination} (USD):")
        for category_name, category in [
            ("accommodation", budget.accommodation),
            ("food", budget.food),
            ("local_transport", budget.local_transport),
            ("activities", budget.activities),
        ]:
            if category:
                lines.append(f"  {category_name}:")
                for key, cost in category.items():
                    url = f" [{cost.source_url}]" if cost.source_url else ""
                    lines.append(f"    {key}: ${cost.amount:.2f}{url}")

    # Group all options by (origin, destination, date_range_label, mode) → collect priced costs.
    # flight/return prices are included but noted as round-trip (count once, not per leg).
    price_ranges: dict[tuple[str, str, str, str], list[float]] = {}
    for route_key, route_knowledge in knowledge.routes.items():
        for date_range, options in route_knowledge.options.items():
            date_label = "any date" if date_range.label == "any" else date_range.label
            for option in options:
                key = (route_key.origin, route_key.destination, date_label, option.mode)
                if option.cost_usd is not None:
                    price_ranges.setdefault(key, []).append(option.cost_usd)

    travel_lines: list[str] = []
    for (origin, destination, date_label, mode), costs in price_ranges.items():
        low, high = min(costs), max(costs)
        cost_str = f"${low:.0f}–${high:.0f}" if high > low else f"${low:.0f}"
        note = " (round-trip price, count once)" if "flight/return" in mode else ""
        travel_lines.append(f"  {origin} to {destination} ({date_label}): {mode} {cost_str}{note}")

    if travel_lines:
        lines.append("\nKnown travel costs (price range per route and mode):")
        lines.extend(travel_lines)

    return "\n".join(lines)
