class ConversationHistory:
    def __init__(self, system_prompt: str):
        self._messages: list[dict] = [{"role": "system", "content": system_prompt}]

    def add_user(self, content: str) -> None:
        self._messages.append({"role": "user", "content": content})

    def add_assistant(self, msg: dict) -> None:
        self._messages.append(msg)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self._messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})

    @property
    def messages(self) -> list[dict]:
        return list(self._messages)
