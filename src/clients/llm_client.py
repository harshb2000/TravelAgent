import json
import re
import time
import uuid
from typing import Any

import httpx

from config.specialist_tuning import resolve_model_config


class LLMError(Exception):
    pass


_RATE_LIMIT_RETRIES = 3


def _retry_after(response_text: str) -> float:
    match = re.search(r"try again in (\d+\.?\d*)s", response_text)
    return float(match.group(1)) if match else 10.0


def _parse_failed_generation(failed_generation: str) -> dict:
    matches = list(re.finditer(r"<function=(\w+)>(.*?)</function>", failed_generation, re.DOTALL))
    if not matches:
        raise LLMError(f"tool_use_failed with no parseable function calls: {failed_generation[:200]!r}")

    content = failed_generation[: matches[0].start()].strip()
    tool_calls = [
        {
            "id": f"call_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {"name": m.group(1), "arguments": m.group(2).strip()},
        }
        for m in matches
    ]
    return {"role": "assistant", "content": content, "tool_calls": tool_calls}


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        extra_headers: dict | None = None,
        endpoint: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.extra_headers = extra_headers or {}
        self.endpoint = endpoint or resolve_model_config(model).endpoint
        if self.endpoint not in {"chat_completions", "responses"}:
            raise ValueError(f"Unsupported LLM endpoint: {self.endpoint}")

    def chat(
        self,
        messages: list[dict],
        timeout: float,
        tools: list[dict] | None = None,
        extra_body: dict[str, Any] | None = None,
        retries: int | None = None,
    ) -> dict:
        if self.endpoint == "responses":
            return self._responses_chat(messages, timeout, tools, extra_body, retries)
        return self._chat_completions(messages, timeout, tools, extra_body, retries)

    def _chat_completions(
        self,
        messages: list[dict],
        timeout: float,
        tools: list[dict] | None,
        extra_body: dict[str, Any] | None,
        retries: int | None,
    ) -> dict:
        body: dict = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if extra_body:
            body.update(extra_body)

        response = self._post("chat/completions", body, timeout, retries)
        if response.status_code == 400:
            error = response.json().get("error", {})
            if error.get("code") == "tool_use_failed":
                return _parse_failed_generation(error.get("failed_generation", ""))
            raise LLMError(f"LLM request failed (400): {response.text}")
        self._check_status(response)

        message = response.json()["choices"][0]["message"]
        message.pop("reasoning", None)
        return message

    def _responses_chat(
        self,
        messages: list[dict],
        timeout: float,
        tools: list[dict] | None,
        extra_body: dict[str, Any] | None,
        retries: int | None,
    ) -> dict:
        instructions, input_items = self._responses_input(messages)
        body: dict = {"model": self.model, "input": input_items}
        if instructions:
            body["instructions"] = instructions
        if tools:
            body["tools"] = self._responses_tools(tools)
            body["tool_choice"] = "auto"
        if extra_body:
            extra = dict(extra_body)
            if "reasoning_effort" in extra:
                effort = extra.pop("reasoning_effort")
                extra.setdefault("reasoning", {"effort": effort})
            body.update(extra)

        response = self._post("responses", body, timeout, retries)
        self._check_status(response)
        return self._responses_message(response.json())

    def _post(self, path: str, body: dict, timeout: float, retries: int | None) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        max_retries = retries if retries is not None else _RATE_LIMIT_RETRIES
        for attempt in range(max_retries + 1):
            response = httpx.post(
                f"{self.base_url}/{path}",
                headers=headers,
                json=body,
                timeout=timeout,
            )
            if response.status_code != 429:
                return response
            if attempt == max_retries:
                raise LLMError(f"LLM request failed (429) after {max_retries} retries: {response.text}")
            time.sleep(_retry_after(response.text))
        raise AssertionError("unreachable")

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        if response.status_code != 200:
            raise LLMError(f"LLM request failed ({response.status_code}): {response.text}")

    @staticmethod
    def _responses_tools(tools: list[dict]) -> list[dict]:
        result = []
        for tool in tools:
            function = tool.get("function")
            if tool.get("type") == "function" and isinstance(function, dict):
                result.append({"type": "function", **function})
            else:
                result.append(tool)
        return result

    @staticmethod
    def _responses_input(messages: list[dict]) -> tuple[str, list[dict]]:
        instructions: list[str] = []
        items: list[dict] = []
        for message in messages:
            role = message.get("role")
            content = _content_text(message.get("content", ""))
            if role == "system":
                if content:
                    instructions.append(content)
            elif role == "assistant":
                raw_output = message.get("_responses_output")
                if raw_output is not None:
                    items.extend(raw_output)
                    continue
                if content:
                    items.append({"role": "assistant", "content": content})
                for tool_call in message.get("tool_calls", []):
                    function = tool_call.get("function", {})
                    items.append({
                        "type": "function_call",
                        "call_id": tool_call.get("id"),
                        "name": function.get("name"),
                        "arguments": function.get("arguments", "{}"),
                    })
            elif role == "tool":
                items.append({
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id"),
                    "output": content,
                })
            else:
                items.append({"role": role, "content": content})
        return "\n\n".join(instructions), items

    @staticmethod
    def _responses_message(data: dict) -> dict:
        output = data.get("output") or []
        content = data.get("output_text") or ""
        tool_calls = []
        if not content:
            content = "".join(
                part.get("text", "")
                for item in output
                if item.get("type") == "message"
                for part in item.get("content", [])
                if part.get("type") in {"output_text", "text"}
            )
        for item in output:
            if item.get("type") != "function_call":
                continue
            arguments = item.get("arguments", "{}")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments)
            tool_calls.append({
                "id": item.get("call_id") or item.get("id"),
                "type": "function",
                "function": {"name": item.get("name"), "arguments": arguments},
            })

        message = {
            "role": "assistant",
            "content": content,
            "finish_reason": "tool_calls" if tool_calls else "stop",
            "_responses_output": output,
        }
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return "" if content is None else str(content)
