from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelConfig:
    extra_headers: dict[str, str] = field(default_factory=dict)
    endpoint: str = "chat_completions"


# Prefix-matched: headers are a model-family property, e.g. any "claude-*" model
# needs the same Anthropic version header regardless of specialist.
_MODEL_CONFIGS: dict[str, ModelConfig] = {
    "claude": ModelConfig(extra_headers={"anthropic-version": "2023-06-01"}),
    "gpt-5.6-luna": ModelConfig(endpoint="responses"),
}
_DEFAULT_MODEL_CONFIG = ModelConfig()


def resolve_model_config(model: str) -> ModelConfig:
    matches = [(prefix, cfg) for prefix, cfg in _MODEL_CONFIGS.items() if model.startswith(prefix)]
    return max(matches, key=lambda pair: len(pair[0]))[1] if matches else _DEFAULT_MODEL_CONFIG


@dataclass(frozen=True)
class SpecialistTuning:
    # Opaque provider-specific body params, e.g. {"reasoning_effort": "low"}, {"think": False},
    # or a token-budget override like {"max_tokens": 2048} (including split completion/reasoning
    # budgets for models that support both, e.g. {"max_completion_tokens": 4096, "thinking": {...}}).
    extra_body: dict[str, Any] = field(default_factory=dict)
    max_iterations: int = 10
    timeout_s: float = 120.0
    retries: int = 3


_SPECIALIST_DEFAULTS: dict[str, SpecialistTuning] = {
    "explorer": SpecialistTuning(max_iterations=3),
    "weather": SpecialistTuning(max_iterations=5),
    "destination_research": SpecialistTuning(max_iterations=4),
    "transportation": SpecialistTuning(max_iterations=5),
    "budget": SpecialistTuning(max_iterations=5),
    "itinerary_planner": SpecialistTuning(max_iterations=6),
    "artifact": SpecialistTuning(max_iterations=5),
    "orchestrator": SpecialistTuning(max_iterations=8),
}

# Exact model-name match: empirically benchmarked values must not silently
# leak onto untested sibling models (e.g. "qwen3:8b" vs "qwen3:32b").
_SPECIALIST_MODEL_OVERRIDES: dict[str, dict[str, SpecialistTuning]] = {
    "explorer": {
        "qwen3.5:9b": SpecialistTuning(extra_body={"reasoning_effort": "none"}, max_iterations=3),
        "gpt-5.6-luna": SpecialistTuning(extra_body={"reasoning": {"effort": "low"}}, max_iterations=3),
    },
    "weather": {
        "qwen3.5:9b": SpecialistTuning(extra_body={"reasoning_effort": "none"}, max_iterations=10),
        "gpt-5.6-luna": SpecialistTuning(extra_body={"reasoning": {"effort": "medium"}}, max_iterations=5),
    },
    "destination_research": {
        "qwen3.5:9b": SpecialistTuning(extra_body={"reasoning_effort": "none"}, max_iterations=4),
        "gpt-5.6-luna": SpecialistTuning(extra_body={"reasoning": {"effort": "medium"}}, max_iterations=4),
    },
    "transportation": {
        "qwen3.5:9b": SpecialistTuning(extra_body={"reasoning_effort": "none"}, max_iterations=5),
        "gpt-5.6-luna": SpecialistTuning(extra_body={"reasoning": {"effort": "high"}}, max_iterations=5),
    },
    "budget": {
        "qwen3.5:9b": SpecialistTuning(extra_body={"reasoning_effort": "none"}, max_iterations=5),
        "gpt-5.6-luna": SpecialistTuning(extra_body={"reasoning": {"effort": "medium"}}, max_iterations=5),
    },
    "itinerary_planner": {
        "qwen3.5:9b": SpecialistTuning(extra_body={"reasoning_effort": "none"}, max_iterations=6),
        "gpt-5.6-luna": SpecialistTuning(extra_body={"reasoning": {"effort": "high"}}, max_iterations=6),
    },
    "artifact": {
        "gpt-5.6-luna": SpecialistTuning(extra_body={"reasoning": {"effort": "medium"}}, max_iterations=5),
    },
    "orchestrator": {
        "qwen3.5:9b": SpecialistTuning(extra_body={"reasoning_effort": "none"}, max_iterations=8),
        "gpt-5.6-luna": SpecialistTuning(extra_body={"reasoning": {"effort": "high"}}, max_iterations=8),
    },
}


def resolve_tuning(specialist: str, model: str) -> SpecialistTuning:
    return _SPECIALIST_MODEL_OVERRIDES.get(specialist, {}).get(model) or _SPECIALIST_DEFAULTS[specialist]
