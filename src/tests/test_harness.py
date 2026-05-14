import json
import time
import pytest
from unittest.mock import MagicMock, patch, call
from clients.llm_client import LLMClient
from tools.base import BaseTool
from agent.harness import SimpleReActAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_llm_client() -> LLMClient:
    return MagicMock(spec=LLMClient)


def stop_response(content: str) -> dict:
    return {"role": "assistant", "content": content, "finish_reason": "stop"}


def tool_call_response(calls: list[dict]) -> dict:
    """calls: list of {"id": ..., "name": ..., "arguments": {...}}"""
    return {
        "role": "assistant",
        "content": None,
        "finish_reason": "tool_calls",
        "tool_calls": [
            {
                "id": c["id"],
                "type": "function",
                "function": {"name": c["name"], "arguments": json.dumps(c.get("arguments", {}))},
            }
            for c in calls
        ],
    }


class EchoTool(BaseTool):
    name = "echo"
    description = "Echoes input back"
    parameters = {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
    }

    def execute(self, **kwargs) -> dict:
        return {"echo": kwargs.get("message", "")}


class SlowTool(BaseTool):
    name = "slow"
    description = "Sleeps briefly"
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.call_times: list[float] = []

    def execute(self, **kwargs) -> dict:
        self.call_times.append(time.time())
        time.sleep(self.delay)
        return {"done": True}


class Slow2Tool(BaseTool):
    name = "slow2"
    description = "Another slow tool"
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.call_times: list[float] = []

    def execute(self, **kwargs) -> dict:
        self.call_times.append(time.time())
        time.sleep(self.delay)
        return {"done": True}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_run_returns_content_on_stop():
    llm = make_llm_client()
    llm.chat.return_value = stop_response("Hello from LLM")
    agent = SimpleReActAgent(llm, [], "system prompt")
    result = agent.run("say hi")
    assert result == "Hello from LLM"


def test_single_tool_call_routed_and_result_in_history():
    echo = EchoTool()
    llm = make_llm_client()
    llm.chat.side_effect = [
        tool_call_response([{"id": "c1", "name": "echo", "arguments": {"message": "hi"}}]),
        stop_response("done"),
    ]
    agent = SimpleReActAgent(llm, [echo], "sys")
    result = agent.run("use echo")
    assert result == "done"
    # second LLM call should have a tool message in the messages list
    second_call_messages = llm.chat.call_args_list[1][0][0]
    tool_msgs = [m for m in second_call_messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert json.loads(tool_msgs[0]["content"]) == {"echo": "hi"}


def test_multiple_tool_calls_dispatched_in_parallel():
    DELAY = 0.08
    slow1 = SlowTool(delay=DELAY)
    slow2 = Slow2Tool(delay=DELAY)
    llm = make_llm_client()
    llm.chat.side_effect = [
        tool_call_response([
            {"id": "c1", "name": "slow", "arguments": {}},
            {"id": "c2", "name": "slow2", "arguments": {}},
        ]),
        stop_response("done"),
    ]
    agent = SimpleReActAgent(llm, [slow1, slow2], "sys")
    start = time.time()
    agent.run("go")
    elapsed = time.time() - start

    # Both tools must have been called exactly once
    assert len(slow1.call_times) == 1
    assert len(slow2.call_times) == 1

    # If truly parallel, both tools started at nearly the same wall-clock time
    start_delta = abs(slow1.call_times[0] - slow2.call_times[0])
    assert start_delta < 0.02, f"Tools started {start_delta*1000:.1f}ms apart — expected near-simultaneous"

    # Total wall time should be well under two sequential delays
    assert elapsed < DELAY * 1.5, f"Expected parallel execution but took {elapsed:.2f}s"


def test_history_grows_across_multiple_run_calls():
    llm = make_llm_client()
    llm.chat.side_effect = [
        stop_response("first answer"),
        stop_response("second answer"),
    ]
    agent = SimpleReActAgent(llm, [], "sys")
    agent.run("first task")
    agent.run("second task")
    # On the second call the messages list should include the first exchange
    second_call_messages = llm.chat.call_args_list[1][0][0]
    contents = [m.get("content") for m in second_call_messages]
    assert "first task" in contents
    assert "first answer" in contents


def test_second_run_sees_tool_results_from_first():
    echo = EchoTool()
    llm = make_llm_client()
    llm.chat.side_effect = [
        tool_call_response([{"id": "c1", "name": "echo", "arguments": {"message": "ping"}}]),
        stop_response("pong"),
        stop_response("remembered"),
    ]
    agent = SimpleReActAgent(llm, [echo], "sys")
    agent.run("task1")
    agent.run("task2")
    third_call_messages = llm.chat.call_args_list[2][0][0]
    tool_msgs = [m for m in third_call_messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1  # tool result from first run is still in history


def test_iterations_hint_injected_before_each_llm_call():
    llm = make_llm_client()
    # First call returns tool use; second returns stop
    llm.chat.side_effect = [
        tool_call_response([{"id": "c1", "name": "echo", "arguments": {"message": "x"}}]),
        stop_response("done"),
    ]
    echo = EchoTool()
    agent = SimpleReActAgent(llm, [echo], "sys", max_iterations=5)
    agent.run("go")

    first_messages = llm.chat.call_args_list[0][0][0]
    second_messages = llm.chat.call_args_list[1][0][0]

    def has_budget_hint(messages: list[dict]) -> bool:
        return any(
            "tool-use rounds remaining" in str(m.get("content", "")).lower()
            or "last tool-use round" in str(m.get("content", "")).lower()
            for m in messages
        )

    assert has_budget_hint(first_messages)
    assert has_budget_hint(second_messages)


def test_final_round_hint_mentions_parallel_and_final_answer():
    llm = make_llm_client()
    llm.chat.return_value = stop_response("ok")
    agent = SimpleReActAgent(llm, [], "sys", max_iterations=1)
    agent.run("go")
    messages = llm.chat.call_args_list[0][0][0]
    all_content = " ".join(str(m.get("content", "")) for m in messages).lower()
    assert "last tool-use round" in all_content
    assert "parallel" in all_content
    assert "final answer" in all_content


def test_exhausted_iterations_forces_final_response():
    echo = EchoTool()
    llm = make_llm_client()
    # Always return tool_calls — never stops on its own
    always_tool = tool_call_response([{"id": "c1", "name": "echo", "arguments": {"message": "x"}}])
    final_stop = stop_response("forced final")
    # max_iterations=2: two tool-call responses, then forced final with no tools
    llm.chat.side_effect = [always_tool, always_tool, final_stop]
    agent = SimpleReActAgent(llm, [echo], "sys", max_iterations=2)
    result = agent.run("go")
    assert result == "forced final"
    # Last call should have been made without tools registered
    last_call_kwargs = llm.chat.call_args_list[-1]
    args, kwargs = last_call_kwargs
    tools_arg = kwargs.get("tools") if kwargs.get("tools") is not None else (args[1] if len(args) > 1 else None)
    assert not tools_arg  # tools must be absent or empty on the forced final call


def test_unknown_tool_name_returns_error():
    llm = make_llm_client()
    llm.chat.side_effect = [
        tool_call_response([{"id": "c1", "name": "nonexistent_tool", "arguments": {}}]),
        stop_response("done"),
    ]
    agent = SimpleReActAgent(llm, [], "sys")
    agent.run("go")
    second_call_messages = llm.chat.call_args_list[1][0][0]
    tool_msgs = [m for m in second_call_messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    result = json.loads(tool_msgs[0]["content"])
    assert result["status"] == "error"
    assert "nonexistent_tool" in result["error"]
