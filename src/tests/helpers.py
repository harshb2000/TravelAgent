"""Shared test utilities for specialist tests."""
import json
from unittest.mock import MagicMock
from clients.llm_client import LLMClient


def make_llm() -> MagicMock:
    return MagicMock(spec=LLMClient)


def stop_msg(content: str) -> dict:
    return {"role": "assistant", "content": content, "finish_reason": "stop"}


def tool_call_msg(calls: list[dict]) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "finish_reason": "tool_calls",
        "tool_calls": [
            {
                "id": c["id"],
                "type": "function",
                "function": {"name": c["name"], "arguments": json.dumps(c.get("args", {}))},
            }
            for c in calls
        ],
    }
