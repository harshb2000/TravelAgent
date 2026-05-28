import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from clients.llm_client import LLMClient
from tools.base import BaseTool
from agent.session import ConversationHistory

_LAST_ROUND_HINT = (
    "[Last tool-use round. You may still call multiple tools in parallel in this response — "
    "they execute simultaneously. After the results come back, provide your final answer directly. "
    "No further tool-use rounds will follow.]"
)


class SimpleReActAgent:
    def __init__(
        self,
        llm_client: LLMClient,
        tools: list[BaseTool],
        system_prompt: str,
        max_iterations: int = 10,
        debug: bool = False,
        reasoning_effort: str | None = None,
    ):
        self._llm = llm_client
        self._tools = {t.name: t for t in tools}
        self._tool_defs = [t.to_llm_definition() for t in tools] if tools else None
        self._max_iterations = max_iterations
        self._history = ConversationHistory(system_prompt)
        self._debug = debug
        self._reasoning_effort = reasoning_effort

    def run(self, task: str) -> str:
        self._history.add_user(task)
        iterations_left = self._max_iterations

        while True:
            is_last = iterations_left <= 1
            tools_to_pass = (self._tool_defs if self._tool_defs and not is_last else None)
            hint = self._iterations_hint(iterations_left, has_tools=tools_to_pass is not None)
            messages = self._history.messages
            # Inject the hint as the last user-role message before the LLM call
            messages_with_hint = messages + [{"role": "user", "content": hint}]

            msg = self._llm.chat(messages_with_hint, tools=tools_to_pass, reasoning_effort=self._reasoning_effort)

            finish_reason = msg.get("finish_reason") or (
                "tool_calls" if msg.get("tool_calls") else "stop"
            )

            if finish_reason == "stop" or not msg.get("tool_calls"):
                self._history.add_assistant(msg)
                return msg.get("content") or ""

            # tool_calls branch
            self._history.add_assistant(msg)
            self._dispatch_tool_calls(msg["tool_calls"])

            iterations_left -= 1
            if iterations_left <= 0:
                # Forced final: call LLM with no tools so it must respond
                final_messages = self._history.messages + [
                    {"role": "user", "content": _LAST_ROUND_HINT}
                ]
                final_msg = self._llm.chat(final_messages, tools=None, reasoning_effort=self._reasoning_effort)
                self._history.add_assistant(final_msg)
                return final_msg.get("content") or ""

    def _dispatch_tool_calls(self, tool_calls: list[dict]) -> None:
        def execute_one(tc: dict) -> tuple[str, str]:
            call_id = tc["id"]
            name = tc["function"]["name"]
            args_raw = tc["function"].get("arguments", "{}")
            try:
                args = json.loads(args_raw)
            except (json.JSONDecodeError, KeyError):
                args = {}

            if self._debug:
                print(f"[debug] → {name}({args_raw[:120]})", file=sys.stderr)

            tool = self._tools.get(name)
            if tool is None:
                result = {"status": "error", "error": f"unknown tool: {name}"}
            else:
                try:
                    result = tool.execute(**args)
                except Exception as e:
                    result = {"status": "error", "error": str(e), "fallback": ""}

            content = json.dumps(result)
            if self._debug:
                print(f"[debug] ← {name}: {content[:200]}", file=sys.stderr)
            return call_id, content

        if len(tool_calls) == 1:
            call_id, content = execute_one(tool_calls[0])
            self._history.add_tool_result(call_id, content)
        else:
            results: dict[str, str] = {}
            with ThreadPoolExecutor() as executor:
                futures = {executor.submit(execute_one, tc): tc["id"] for tc in tool_calls}
                for future in as_completed(futures):
                    call_id, content = future.result()
                    results[call_id] = content
            # Append in original call order so history is deterministic
            for tc in tool_calls:
                self._history.add_tool_result(tc["id"], results[tc["id"]])

    @staticmethod
    def _iterations_hint(remaining: int, has_tools: bool) -> str:
        if remaining <= 1:
            return _LAST_ROUND_HINT
        if not has_tools:
            return f"[Iterations remaining: {remaining}.]"
        return (
            f"[Tool-use rounds remaining: {remaining}. "
            f"You may call multiple tools in a single response — they execute in parallel. "
            f"Plan your tool use to finish within this budget.]"
        )
