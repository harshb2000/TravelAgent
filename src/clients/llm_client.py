import re
import time
import uuid
from typing import Any

import httpx


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
        extra_headers: dict = {},
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.extra_headers = extra_headers

    def chat(
        self,
        messages: list[dict],
        timeout: float,
        tools: list[dict] | None = None,
        extra_body: dict[str, Any] | None = None,
        retries: int | None = None,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        body: dict = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if extra_body:
            body.update(extra_body)

        max_retries = retries if retries is not None else _RATE_LIMIT_RETRIES
        for attempt in range(max_retries + 1):
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=body,
                timeout=timeout,
            )
            if response.status_code != 429:
                break
            if attempt == max_retries:
                raise LLMError(f"LLM request failed (429) after {max_retries} retries: {response.text}")
            wait = _retry_after(response.text)
            time.sleep(wait)

        if response.status_code == 400:
            error = response.json().get("error", {})
            if error.get("code") == "tool_use_failed":
                return _parse_failed_generation(error.get("failed_generation", ""))
            raise LLMError(f"LLM request failed (400): {response.text}")

        if response.status_code != 200:
            raise LLMError(f"LLM request failed ({response.status_code}): {response.text}")

        message = response.json()["choices"][0]["message"]
        message.pop("reasoning", None)
        return message
