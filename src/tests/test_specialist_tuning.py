from config.specialist_tuning import (
    _MODEL_CONFIGS,
    _SPECIALIST_DEFAULTS,
    _SPECIALIST_MODEL_OVERRIDES,
    ModelConfig,
    resolve_model_config,
    resolve_tuning,
)


# ---------------------------------------------------------------------------
# resolve_tuning
# ---------------------------------------------------------------------------

def test_resolve_tuning_falls_back_to_default_for_untuned_model():
    for specialist, default in _SPECIALIST_DEFAULTS.items():
        assert resolve_tuning(specialist, "some-untuned-model") == default


def test_resolve_tuning_matches_migration_table():
    for specialist, overrides in _SPECIALIST_MODEL_OVERRIDES.items():
        for model, expected in overrides.items():
            assert resolve_tuning(specialist, model) == expected


def test_resolve_tuning_override_replaces_whole_entry_not_merged():
    tuning = resolve_tuning("itinerary_planner", "qwen3.5:9b")
    default = _SPECIALIST_DEFAULTS["itinerary_planner"]
    # override sets max_iterations explicitly even though it matches the default value;
    # the returned object must be the override instance, not a merge of the two
    assert tuning is _SPECIALIST_MODEL_OVERRIDES["itinerary_planner"]["qwen3.5:9b"]
    assert tuning.extra_body == {"reasoning_effort": "none"}
    assert default.extra_body == {}


# ---------------------------------------------------------------------------
# resolve_model_config
# ---------------------------------------------------------------------------

def test_resolve_model_config_no_match_returns_default():
    cfg = resolve_model_config("qwen3.5:9b")
    assert cfg.extra_headers == {}


def test_resolve_model_config_matches_claude_prefix():
    cfg = resolve_model_config("claude-sonnet-4-6")
    assert cfg.extra_headers == {"anthropic-version": "2023-06-01"}
    assert cfg.endpoint == "chat_completions"


def test_resolve_model_config_uses_responses_for_gpt_luna():
    assert resolve_model_config("gpt-5.6-luna").endpoint == "responses"


def test_resolve_model_config_longest_prefix_wins(monkeypatch):
    monkeypatch.setitem(_MODEL_CONFIGS, "foo", ModelConfig(extra_headers={"x": "short"}))
    monkeypatch.setitem(_MODEL_CONFIGS, "foo-bar", ModelConfig(extra_headers={"x": "long"}))

    cfg = resolve_model_config("foo-bar-baz")
    assert cfg.extra_headers == {"x": "long"}
