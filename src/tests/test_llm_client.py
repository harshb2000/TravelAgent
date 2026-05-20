import json
import pytest
import httpx
from unittest.mock import patch, MagicMock
from clients.llm_client import LLMClient, LLMError
from agent.session import ConversationHistory


# ---------------------------------------------------------------------------
# LLMClient tests
# ---------------------------------------------------------------------------

def _make_response(message: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = {"choices": [{"message": message}]}
    return resp


def test_chat_returns_assistant_message():
    client = LLMClient("https://api.example.com/v1", "key", "model-x")
    expected = {"role": "assistant", "content": "hello", "finish_reason": "stop"}
    with patch("httpx.post", return_value=_make_response(expected)) as mock_post:
        result = client.chat([{"role": "user", "content": "hi"}])
    assert result == expected
    mock_post.assert_called_once()


def test_chat_passes_extra_headers():
    extra = {"anthropic-version": "2023-06-01"}
    client = LLMClient("https://api.example.com/v1", "key", "model-x", extra_headers=extra)
    expected = {"role": "assistant", "content": "hi"}
    with patch("httpx.post", return_value=_make_response(expected)) as mock_post:
        client.chat([{"role": "user", "content": "hi"}])
    _, kwargs = mock_post.call_args
    sent_headers = kwargs.get("headers", {})
    assert sent_headers.get("anthropic-version") == "2023-06-01"


def test_chat_raises_llm_error_on_non_200():
    client = LLMClient("https://api.example.com/v1", "key", "model-x")
    error_resp = MagicMock(spec=httpx.Response)
    error_resp.status_code = 401
    error_resp.text = "Unauthorized"
    with patch("httpx.post", return_value=error_resp):
        with pytest.raises(LLMError):
            client.chat([{"role": "user", "content": "hi"}])


def test_chat_sends_tools_when_provided():
    client = LLMClient("https://api.example.com/v1", "key", "model-x")
    tools = [{"type": "function", "function": {"name": "search", "description": "", "parameters": {}}}]
    expected = {"role": "assistant", "content": None, "tool_calls": []}
    with patch("httpx.post", return_value=_make_response(expected)) as mock_post:
        client.chat([{"role": "user", "content": "hi"}], tools=tools)
    _, kwargs = mock_post.call_args
    body = kwargs.get("json", {})
    assert "tools" in body
    assert body["tools"] == tools


# ---------------------------------------------------------------------------
# ConversationHistory tests
# ---------------------------------------------------------------------------

def test_add_tool_result_appends_tool_message():
    h = ConversationHistory("system")
    h.add_tool_result("call_abc", '{"result": 42}')
    last = h.messages[-1]
    assert last["role"] == "tool"
    assert last["tool_call_id"] == "call_abc"
    assert last["content"] == '{"result": 42}'


def test_messages_order_is_correct():
    h = ConversationHistory("sys")
    h.add_user("q1")
    h.add_assistant({"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]})
    h.add_tool_result("c1", "result")
    h.add_assistant({"role": "assistant", "content": "done"})
    roles = [m["role"] for m in h.messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
