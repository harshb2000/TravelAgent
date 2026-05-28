import json
import pytest
import httpx
from unittest.mock import patch, MagicMock, call
from clients.llm_client import LLMClient, LLMError, _parse_failed_generation, _retry_after, _supports_reasoning_effort
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


def _make_error_response(code: str, failed_generation: str = "", status_code: int = 400) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = code
    resp.json.return_value = {
        "error": {"code": code, "message": "...", "failed_generation": failed_generation}
    }
    return resp


def test_parse_failed_generation_single_call():
    msg = _parse_failed_generation('<function=search>{"query": "Japan"}</function>')
    assert msg["role"] == "assistant"
    assert msg["content"] == ""
    assert len(msg["tool_calls"]) == 1
    tc = msg["tool_calls"][0]
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "search"
    assert json.loads(tc["function"]["arguments"]) == {"query": "Japan"}


def test_parse_failed_generation_with_preamble():
    msg = _parse_failed_generation(
        'Sure, let me look that up. <function=search>{"query": "flights"}</function>'
    )
    assert msg["content"] == "Sure, let me look that up."
    assert msg["tool_calls"][0]["function"]["name"] == "search"


def test_parse_failed_generation_multiple_calls():
    raw = '<function=search>{"query": "a"}</function><function=weather>{"city": "Tokyo"}</function>'
    msg = _parse_failed_generation(raw)
    assert len(msg["tool_calls"]) == 2
    assert msg["tool_calls"][0]["function"]["name"] == "search"
    assert msg["tool_calls"][1]["function"]["name"] == "weather"
    ids = {tc["id"] for tc in msg["tool_calls"]}
    assert len(ids) == 2  # unique IDs


def test_parse_failed_generation_no_calls_raises():
    with pytest.raises(LLMError):
        _parse_failed_generation("I cannot help with that.")


def test_chat_recovers_from_tool_use_failed():
    client = LLMClient("https://api.example.com/v1", "key", "model-x")
    raw = '<function=search>{"query": "Japan"}</function>'
    with patch("httpx.post", return_value=_make_error_response("tool_use_failed", raw)):
        result = client.chat([{"role": "user", "content": "find flights"}])
    assert result["role"] == "assistant"
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["function"]["name"] == "search"


def _make_429_response(wait_seconds: float = 5.0) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 429
    resp.text = f"Rate limit reached. Please try again in {wait_seconds}s."
    resp.json.return_value = {"error": {"code": "rate_limit_exceeded", "message": resp.text}}
    return resp


def test_supports_reasoning_effort_known_prefixes():
    assert _supports_reasoning_effort("qwen3:8b")
    assert _supports_reasoning_effort("qwen3:32b")
    assert _supports_reasoning_effort("o1-mini")
    assert _supports_reasoning_effort("o3")
    assert _supports_reasoning_effort("o4-turbo")


def test_supports_reasoning_effort_unknown_model():
    assert not _supports_reasoning_effort("llama-3.3-70b-versatile")
    assert not _supports_reasoning_effort("gpt-4o")
    assert not _supports_reasoning_effort("claude-3-5-sonnet")


def test_chat_includes_reasoning_effort_for_supported_model():
    client = LLMClient("https://api.example.com/v1", "key", "qwen3:8b")
    ok_msg = {"role": "assistant", "content": "hi"}
    with patch("httpx.post", return_value=_make_response(ok_msg)) as mock_post:
        client.chat([{"role": "user", "content": "hi"}], reasoning_effort="low")
    body = mock_post.call_args.kwargs["json"]
    assert body.get("reasoning_effort") == "low"


def test_chat_omits_reasoning_effort_for_unsupported_model():
    client = LLMClient("https://api.example.com/v1", "key", "llama-3.3-70b-versatile")
    ok_msg = {"role": "assistant", "content": "hi"}
    with patch("httpx.post", return_value=_make_response(ok_msg)) as mock_post:
        client.chat([{"role": "user", "content": "hi"}], reasoning_effort="low")
    body = mock_post.call_args.kwargs["json"]
    assert "reasoning_effort" not in body


def test_retry_after_parses_seconds():
    assert _retry_after("Please try again in 31.985s.") == pytest.approx(31.985)


def test_retry_after_fallback_on_no_match():
    assert _retry_after("no timing info here") == 10.0


def test_chat_retries_on_429_then_succeeds():
    client = LLMClient("https://api.example.com/v1", "key", "model-x")
    ok_msg = {"role": "assistant", "content": "hi"}
    with patch("httpx.post", side_effect=[_make_429_response(0.01), _make_response(ok_msg)]) as mock_post:
        with patch("time.sleep") as mock_sleep:
            result = client.chat([{"role": "user", "content": "hi"}])
    assert result == ok_msg
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once_with(pytest.approx(0.01))


def test_chat_raises_after_max_retries_on_429():
    client = LLMClient("https://api.example.com/v1", "key", "model-x")
    with patch("httpx.post", return_value=_make_429_response(0.01)):
        with patch("time.sleep"):
            with pytest.raises(LLMError, match="429"):
                client.chat([{"role": "user", "content": "hi"}])


def test_chat_raises_on_400_other_error():
    client = LLMClient("https://api.example.com/v1", "key", "model-x")
    with patch("httpx.post", return_value=_make_error_response("invalid_request_error")):
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
