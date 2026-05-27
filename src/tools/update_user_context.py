from models.knowledge_state import UserContext
from tools.base import BaseTool


class UpdateUserContextTool(BaseTool):
    name = "update_user_context"
    description = (
        "Update the user's trip intent, preferences, and constraints. "
        "Call this first whenever the user provides new or revised trip information, "
        "then call specialist tools as needed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "context": {
                "type": "string",
                "description": (
                    "The user's full trip intent as a clear, updated statement. "
                    "Express negative constraints as explicit phrases: "
                    "'not Thailand', 'avoid beaches', 'no nightlife' — not buried in prose."
                ),
            },
        },
        "required": ["context"],
    }

    def __init__(self, user_context: UserContext):
        self._user_context = user_context

    def execute(self, **kwargs) -> dict:
        self._user_context.context = kwargs["context"]
        return {"status": "ok"}
