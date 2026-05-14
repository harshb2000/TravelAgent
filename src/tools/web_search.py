from tools.base import BaseTool
from models.search import WebSearchOutput
from clients.search_client import SearchClient


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web for current information on any topic. "
        "Use depth='advanced' for detailed research (costs more quota); 'basic' for quick lookups."
    )
    output_model = WebSearchOutput
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "depth": {
                "type": "string",
                "enum": ["basic", "advanced"],
                "description": "'advanced' for detailed research, 'basic' for quick lookups. Defaults to 'basic'.",
            },
            "max_results": {
                "type": "integer",
                "description": "Number of results to return (default 5, max 10)",
            },
        },
        "required": ["query"],
    }

    def __init__(self, search_client: SearchClient):
        self._client = search_client

    def execute(self, **kwargs) -> dict:
        query: str = kwargs["query"]
        depth: str = kwargs.get("depth", "basic")
        max_results: int = kwargs.get("max_results", 5)

        try:
            result = self._client.search(query=query, depth=depth, max_results=max_results)
            return self._validated_output(result)
        except Exception as e:
            return {"status": "error", "error": str(e), "fallback": "", "results": []}
