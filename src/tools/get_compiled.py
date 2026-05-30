from models.knowledge_state import KnowledgeState, DateRange, RouteKey
from tools.base import BaseTool
from tools.transportation_wrapper import bfs_find_path, bfs_distances


class GetResearchCompiledTool(BaseTool):
    name = "get_research_compiled"
    description = "Fetch full compiled research for a destination from KnowledgeState, with inline source links."
    parameters = {
        "type": "object",
        "properties": {
            "destination": {"type": "string", "description": "Destination city name."},
        },
        "required": ["destination"],
    }

    def __init__(self, knowledge: KnowledgeState):
        self._knowledge = knowledge

    def execute(self, **kwargs) -> dict:
        destination: str = kwargs["destination"]
        dk = self._knowledge.destinations.get(destination)
        if not dk or not dk.research:
            return {"result": f"No research data found for {destination}. Call DestinationResearchSpecialist first."}
        r = dk.research
        lines = [f"# Research: {destination} ({r.country})"]
        lines.append(f"**Vibe:** {r.vibe}")
        if r.top_attractions:
            lines.append(f"**Top attractions:** {', '.join(r.top_attractions)}")
        if r.summary:
            lines.append(f"**Summary:** {r.summary}")
        if r.safety_summary:
            url = f" [source]({r.safety_summary.source_url})" if r.safety_summary.source_url else ""
            lines.append(f"**Safety:** {r.safety_summary.text}{url}")
        if r.visa_complexity:
            lines.append("**Visa complexity:**")
            for profile, swa in r.visa_complexity.items():
                url = f" [source]({swa.source_url})" if swa.source_url else ""
                lines.append(f"  {profile}: {swa.text}{url}")
        if r.festivals:
            lines.append(f"**Festivals:** {', '.join(r.festivals)}")
        if r.notable_areas:
            lines.append("**Notable Areas:**")
            for name, na in r.notable_areas.items():
                url = f" [source]({na.source_url})" if na.source_url else ""
                highlights = " — " + ", ".join(na.highlights) if na.highlights else ""
                lines.append(f"  {name}: {na.description}{highlights}{url}")
        if r.activities:
            lines.append("**Activities:**")
            for act in r.activities:
                tags = ", ".join(act.tags) if act.tags else "—"
                indoor = "indoor" if act.indoor else "outdoor"
                dur = f"{act.duration_min}min" if act.duration_min else "duration unknown"
                url = f" [source]({act.source_url})" if act.source_url else ""
                lines.append(f"  {act.name} [{tags}] ({indoor}, {dur}){url}")
        return {"result": "\n".join(lines)}


class GetBudgetCompiledTool(BaseTool):
    name = "get_budget_compiled"
    description = "Fetch full compiled budget data for a destination from KnowledgeState, with inline source links."
    parameters = {
        "type": "object",
        "properties": {
            "destination": {"type": "string", "description": "Destination city name."},
        },
        "required": ["destination"],
    }

    def __init__(self, knowledge: KnowledgeState):
        self._knowledge = knowledge

    def execute(self, **kwargs) -> dict:
        destination: str = kwargs["destination"]
        dk = self._knowledge.destinations.get(destination)
        if not dk or not dk.budget:
            return {"result": f"No budget data found for {destination}. Call BudgetSpecialist first."}
        budget = dk.budget
        lines = [f"# Budget: {destination} (all amounts in USD)"]
        for category_name, category in [
            ("accommodation", budget.accommodation),
            ("food", budget.food),
            ("local_transport", budget.local_transport),
            ("activities", budget.activities),
        ]:
            if category:
                lines.append(f"**{category_name}:**")
                for key, cost in category.items():
                    url = f" [source]({cost.source_url})" if cost.source_url else ""
                    lines.append(f"  {key}: ${cost.amount:.2f}{url}")
        return {"result": "\n".join(lines)}


class GetWeatherCompiledTool(BaseTool):
    name = "get_weather_compiled"
    description = "Fetch weather data for a destination and date range from KnowledgeState."
    parameters = {
        "type": "object",
        "properties": {
            "destination": {"type": "string", "description": "Destination city name."},
            "date_range": {"type": "string", "description": "Date range label, e.g. 'June 2026'."},
        },
        "required": ["destination"],
    }

    def __init__(self, knowledge: KnowledgeState):
        self._knowledge = knowledge

    def execute(self, **kwargs) -> dict:
        destination: str = kwargs["destination"]
        date_range_str: str = kwargs.get("date_range", "")
        dk = self._knowledge.destinations.get(destination)
        if not dk or not dk.weather:
            return {"result": f"No weather data found for {destination}. Call WeatherSpecialist first."}

        target_dr = DateRange.from_string(date_range_str) if date_range_str else None
        entries = (
            [(target_dr, dk.weather[target_dr])]
            if target_dr and target_dr in dk.weather
            else list(dk.weather.items())
        )

        lines = [f"# Weather: {destination}"]
        for dr, wo in entries:
            lines.append(f"## {dr.label} ({wo.mode})")
            for day in wo.days:
                precip = ""
                if day.precipitation_prob is not None:
                    precip = f", {day.precipitation_prob}% precip prob"
                elif day.precipitation_sum is not None:
                    precip = f", {day.precipitation_sum:.1f}mm"
                desc = f" — {day.weather_description}" if day.weather_description else ""
                lines.append(f"  {day.date}: {day.temp_min:.0f}–{day.temp_max:.0f}°C{precip}{desc}")
        return {"result": "\n".join(lines)}


class GetRouteCompiledTool(BaseTool):
    name = "get_route_compiled"
    description = "Fetch all travel options for a composed path from origin to destination from KnowledgeState."
    parameters = {
        "type": "object",
        "properties": {
            "origin": {"type": "string", "description": "Origin city or airport name."},
            "destination": {"type": "string", "description": "Destination city or airport name."},
            "date_range": {"type": "string", "description": "Date range label, e.g. 'Jul 2026'."},
        },
        "required": ["origin", "destination"],
    }

    def __init__(self, knowledge: KnowledgeState):
        self._knowledge = knowledge

    def execute(self, **kwargs) -> dict:
        origin: str = kwargs["origin"]
        destination: str = kwargs["destination"]
        date_range_str: str = kwargs.get("date_range", "any")
        date_range = DateRange.from_string(date_range_str)
        any_dr = DateRange("any")
        routes = self._knowledge.routes

        # Check reachability
        if bfs_find_path(origin, destination, date_range, routes) is None:
            return {"result": f"No route found from {origin} to {destination}. Call TransportationSpecialist first."}

        # Build forward and reverse graphs to find all edges on any valid path
        forward_graph: dict[str, set[str]] = {}
        reverse_graph: dict[str, set[str]] = {}
        for rk, rk_knowledge in routes.items():
            if any(dr in (date_range, any_dr) for dr in rk_knowledge.options):
                forward_graph.setdefault(rk.origin, set()).add(rk.destination)
                reverse_graph.setdefault(rk.destination, set()).add(rk.origin)

        forward_dist = bfs_distances(origin, forward_graph)
        backward_dist = bfs_distances(destination, reverse_graph)

        edges_by_level: dict[int, list[RouteKey]] = {}
        for rk, rk_knowledge in routes.items():
            if not any(dr in (date_range, any_dr) for dr in rk_knowledge.options):
                continue
            if rk.origin not in forward_dist or rk.destination not in backward_dist:
                continue
            level = forward_dist[rk.origin]
            edges_by_level.setdefault(level, []).append(rk)

        lines = [f"# Route: {origin} → {destination} ({date_range.label})"]
        for level in sorted(edges_by_level):
            for rk in edges_by_level[level]:
                rk_knowledge = routes[rk]
                lines.append(f"\n**{rk.origin} → {rk.destination}:**")
                for stored_dr, options in rk_knowledge.options.items():
                    if stored_dr not in (date_range, any_dr) or not options:
                        continue
                    for option in options:
                        url = f" [source]({option.source_url})" if option.source_url else ""
                        cost = f"${option.cost_usd:.0f}" if option.cost_usd is not None else "cost unknown"
                        dur = f", {option.duration_min}min" if option.duration_min else ""
                        operator = f" · {option.operator}" if option.operator else ""
                        lines.append(f"  {option.mode}{operator}: {cost}{dur}{url}")
        return {"result": "\n".join(lines)}


class GetCandidatesCompiledTool(BaseTool):
    name = "get_candidates_compiled"
    description = "Fetch all destination candidates with rationale and source links from KnowledgeState."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, knowledge: KnowledgeState):
        self._knowledge = knowledge

    def execute(self, **kwargs) -> dict:
        if not self._knowledge.candidates:
            return {"result": "No destination candidates found. Call ExplorerSpecialist first."}
        lines = ["# Destination Candidates"]
        for c in self._knowledge.candidates:
            tags = ", ".join(c.vibe_tags) if c.vibe_tags else "—"
            url = f" [source]({c.source_url})" if c.source_url else ""
            lines.append(f"\n**{c.name}** ({c.country}) [{tags}]{url}")
            if c.rationale:
                lines.append(f"  {c.rationale}")
        return {"result": "\n".join(lines)}
