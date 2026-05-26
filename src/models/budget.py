from __future__ import annotations

from pydantic import BaseModel

from models.knowledge_state import DestinationBudget


class BudgetSpecialistOutput(BaseModel):
    destination_budget: DestinationBudget | None = None
    breakdown: str
