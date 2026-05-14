from pydantic import BaseModel, Field


class CalculateOutput(BaseModel):
    result: float = Field(description="Numeric result of the expression")
    label: str = Field(description="Label provided in the request, for context")
