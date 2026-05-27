from __future__ import annotations

from pydantic import BaseModel, Field

from models.knowledge_state import DestinationBudget, Itinerary, Activity


class BudgetSpecialistOutput(BaseModel):
    destination_budget: DestinationBudget | None = None
    breakdown: str


class ItineraryPlannerOutput(BaseModel):
    itinerary: Itinerary = Field(description="The full day-by-day itinerary.")
    activity_updates: dict[str, list[Activity]] = Field(default_factory=dict, description="Destination → enriched Activity list discovered during venue research. Empty dict if no new activities found.")


class ArtifactOutput(BaseModel):
    file_path: str | None = Field(default=None, description="Path to the written artifact file. Null when missing_data is set.")
    missing_data: list[str] | None = Field(default=None, description="Major KnowledgeState gaps that must be resolved before the document can be generated — e.g. 'full-depth destination research for Tokyo', 'itinerary for Tokyo and Kyoto'. Set this instead of writing the file. Null when file_path is set.")
