import warnings
from pydantic import BaseModel, ConfigDict
from tavily import TavilyClient

_CALL_COUNT_WARNING_THRESHOLD = 900


# ---------------------------------------------------------------------------
# Raw API models — describes what Tavily returns for the fields we use.
# ---------------------------------------------------------------------------

class _TavilyResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str
    url: str
    content: str
    score: float


class _TavilyResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    results: list[_TavilyResult] = []
    answer: str | None = None


class SearchClient:
    def __init__(self, api_key: str):
        self._client = TavilyClient(api_key=api_key)
        self.call_count = 0

    def search(self, query: str, depth: str = "basic", max_results: int = 5) -> dict:
        self.call_count += 1
        if self.call_count == _CALL_COUNT_WARNING_THRESHOLD:
            warnings.warn(
                f"Tavily call count has reached {_CALL_COUNT_WARNING_THRESHOLD} — approaching free-tier limit.",
                stacklevel=2,
            )

        raw = self._client.search(
            query=query,
            search_depth=depth,
            max_results=max_results,
            include_answer=True,
        )
        response = _TavilyResponse.model_validate(raw)

        out: dict = {
            "results": [
                {"title": r.title, "url": r.url, "content": r.content, "score": r.score}
                for r in response.results
            ]
        }
        if response.answer:
            out["answer"] = response.answer
        return out
