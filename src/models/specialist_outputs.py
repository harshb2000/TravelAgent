from __future__ import annotations

from pydantic import BaseModel, Field

from models.knowledge_state import DestinationBudget, Itinerary, Activity


class BudgetSpecialistOutput(BaseModel):
    destination_budget: DestinationBudget | None = Field(
        default=None,
        description="Per-category destination costs (accommodation, food, local transport, activities) discovered via web_search, all amounts in USD. Set to null when no web_search calls were made — the calling system merges this additively into session state.",
    )
    breakdown: str = Field(
        description="Formatted multi-line cost breakdown. Show each category with per-unit rate and scaled total (accommodation per room/night × nights; food per person/day × party size × days; activities per person × party size). When home currency is known, show USD total and home-currency equivalent at the stated exchange rate. When a total budget is stated, show the delta.",
    )


class ItineraryPlannerOutput(BaseModel):
    itinerary: Itinerary = Field(description="The full day-by-day itinerary.")
    activity_updates: dict[str, list[Activity]] = Field(default_factory=dict, description="Dictionary of destination to enriched Activity list. Must include an entry for every activity placed in the itinerary, whether from destination research or newly introduced. Enrich each entry with duration_min, indoor, and source_url from web_search results.")


class ArtifactOutput(BaseModel):
    file_path: str | None = Field(default=None, description="Path to the written artifact file, as returned by the file_write tool. Must exactly match that return value — do not fabricate a path. Null when missing_data is set.")
    missing_data: list[str] | None = Field(default=None, description="Major knowledge gaps that must be resolved before the document can be generated. Describe each gap in plain English naming the specific destination or section, e.g. 'full-depth destination research for Kyoto', 'day-by-day itinerary for Tokyo and Kyoto'. Set this instead of file_path. Null when file_path is set. Exactly one of file_path or missing_data must be set — never both, never neither.")
