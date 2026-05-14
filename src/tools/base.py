import json
from abc import ABC, abstractmethod
from pydantic import BaseModel, ValidationError


class BaseTool(ABC):
    name: str
    description: str
    parameters: dict
    output_model: type[BaseModel] | None = None

    @abstractmethod
    def execute(self, **kwargs) -> dict:
        pass

    def _validated_output(self, result: dict) -> dict:
        """Validate a success result through output_model before returning to the agent.
        Pass error dicts through unchanged."""
        if self.output_model is None or result.get("status") == "error":
            return result
        try:
            return self.output_model.model_validate(result).model_dump()
        except ValidationError as e:
            return {"status": "error", "error": f"Output validation failed: {e}", "fallback": ""}

    def to_llm_definition(self) -> dict:
        description = self.description
        if self.output_model:
            schema = self.output_model.model_json_schema()
            description += (
                f"\n\nSuccess output schema: {json.dumps(schema)}"
                '\n\nOn error: {"status": "error", "error": "<message>", "fallback": "<suggestion>"}'
            )
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": description,
                "parameters": self.parameters,
            },
        }
