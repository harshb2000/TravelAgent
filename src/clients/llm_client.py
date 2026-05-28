import re
import time
import uuid
import httpx


class LLMError(Exception):
    pass


# Models that accept a `reasoning_effort` parameter in the request body.
# Checked by prefix so variants like "qwen3:8b" and "qwen3:32b" both match "qwen3".
_REASONING_EFFORT_MODELS: frozenset[str] = frozenset({
    "qwen3",
    "o1",
    "o3",
    "o4",
})


def _supports_reasoning_effort(model: str) -> bool:
    return any(model.startswith(prefix) for prefix in _REASONING_EFFORT_MODELS)


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
    def __init__(self, base_url: str, api_key: str, model: str, extra_headers: dict = {}):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.extra_headers = extra_headers

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        reasoning_effort: str | None = None,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        body: dict = {"model": self.model, "messages": messages, "max_tokens": 4096}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if reasoning_effort is not None and _supports_reasoning_effort(self.model):
            body["reasoning_effort"] = reasoning_effort

        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=body,
                timeout=120.0,
            )
            if response.status_code != 429:
                break
            if attempt == _RATE_LIMIT_RETRIES:
                raise LLMError(f"LLM request failed (429) after {_RATE_LIMIT_RETRIES} retries: {response.text}")
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
