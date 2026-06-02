from models.knowledge_state import KnowledgeState, UserContext
from specialists.budget import BudgetSpecialist
from tools.base import BaseTool


class BudgetWrapperTool(BaseTool):
    name = "budget"
    description = (
        "Calculate a detailed trip budget — accommodation, food, local transport, and activities — "
        "incorporating any flight costs already researched this session. "
        "Returns a formatted cost breakdown with totals in USD and home currency."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Free-form trip configuration string. "
                    "Include traveller count, trip duration, accommodation tier, home currency or budget "
                    "target, and origin city for flights. "
                    "Example: '2 people, 7 nights Tokyo late June, flying Mumbai round-trip, "
                    "mid-range hotel, budget ₹2.5L/person'."
                ),
            },
            "destination": {
                "type": "string",
                "description": "Entity-level destination name.",
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

        dk = self._knowledge.destinations.get(destination)
        existing_budget = dk.budget if dk else None
        travel_costs = _build_travel_costs(self._knowledge)

        try:
            result = self._specialist.run(
                query,
                user_context=self._user_context.context,
                existing_budget=existing_budget,
                travel_costs=travel_costs,
            )
        except Exception as e:
            return {"status": "error", "summary": f"BudgetSpecialist failed: {e}"}

        if result.destination_budget is not None:
            self._knowledge.update_destination_budget(destination, result.destination_budget)

        return {"status": "ok", "summary": result.breakdown}


def _build_travel_costs(knowledge: KnowledgeState) -> str | None:
    price_ranges: dict[tuple[str, str, str, str], list[float]] = {}
    for route_key, route_knowledge in knowledge.routes.items():
        for date_range, options in route_knowledge.options.items():
            date_label = "any date" if date_range.label == "any" else date_range.label
            for option in options:
                key = (route_key.origin, route_key.destination, date_label, option.mode)
                if option.cost_usd is not None:
                    price_ranges.setdefault(key, []).append(option.cost_usd)

    lines: list[str] = []
    for (origin, dest, date_label, mode), costs in price_ranges.items():
        low, high = min(costs), max(costs)
        cost_str = f"${low:.0f}–${high:.0f}" if high > low else f"${low:.0f}"
        note = " (round-trip price, count once)" if "flight/return" in mode else ""
        lines.append(f"  {origin} to {dest} ({date_label}): {mode} {cost_str}{note}")

    return "\n".join(lines) if lines else None
