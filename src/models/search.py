from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    title: str = Field(description="Page title")
    url: str = Field(description="Source URL")
    content: str = Field(description="Relevant snippet — clean text, not HTML")
    score: float = Field(description="Relevance score 0–1")


class WebSearchOutput(BaseModel):
    results: list[SearchResult] = Field(description="Ranked list of matching pages")
    answer: str | None = Field(default=None, description="Synthesised answer string when available; null otherwise")
