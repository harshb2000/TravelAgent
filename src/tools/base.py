import json
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pydantic import BaseModel, ValidationError
from notifications import ProgressNotifier


class BaseTool(ABC):
    name: str
    description: str
    parameters: dict
    output_model: type[BaseModel] | None = None
    progress_level: int = 2
    progress_notifier: ProgressNotifier | None = None

    def start_progress(self, arguments: dict) -> str | None:
        if not self.progress_notifier:
            return None
        return self.progress_notifier.generated(
            level=self.progress_level,
            name=self.name,
            description=self.description,
            arguments=arguments,
        )

    def notify_static_pending(self, label: str, level: int = 2) -> str | None:
        if not self.progress_notifier:
            return None
        return self.progress_notifier.static_pending(level=level, label=label)

    def notify_static_resolved(self, entry_id: str | None) -> None:
        if self.progress_notifier and entry_id:
            self.progress_notifier.resolve(entry_id)

    @contextmanager
    def static_progress(self, label: str, level: int = 2):
        entry_id = self.notify_static_pending(label, level)
        try:
            yield
        finally:
            self.notify_static_resolved(entry_id)

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
