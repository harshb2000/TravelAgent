from clients.llm_client import LLMClient
from tools.base import BaseTool


class SelfCritiqueTool(BaseTool):
    name = "self_critique"
    description = (
        "Critique a draft travel document against the user's original request. "
        "Returns structured feedback: missing sections, factual inconsistencies, "
        "formatting issues, and tone. Always call before file_write to improve quality."
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The full draft document content to critique.",
            },
            "query": {
                "type": "string",
                "description": "The user's original artifact request.",
            },
        },
        "required": ["content", "query"],
    }

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    def execute(self, **kwargs) -> dict:
        content: str = kwargs["content"]
        query: str = kwargs["query"]
        messages = [
            {
                "role": "user",
                "content": (
                    f"Review this travel document against the user's request.\n\n"
                    f"User request: {query}\n\n"
                    f"Document:\n{content}\n\n"
                    "Identify: missing sections, factual inconsistencies, formatting issues, tone. "
                    "Be specific and actionable."
                ),
            }
        ]
        response = self._llm.chat(messages)
        critique = response.get("content") or ""
        return {"critique": critique}
