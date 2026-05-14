import json
import httpx


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, extra_headers: dict = {}):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.extra_headers = extra_headers

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        body: dict = {"model": self.model, "messages": messages, "max_tokens": 4096}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=body,
            timeout=120.0,
        )

        if response.status_code != 200:
            raise LLMError(f"LLM request failed ({response.status_code}): {response.text}")

        return response.json()["choices"][0]["message"]
