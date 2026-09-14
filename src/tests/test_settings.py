import importlib
from pathlib import Path


def test_env_file_is_independent_of_working_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test")
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setenv("LLM_MODEL", "test")
    monkeypatch.setenv("PROGRESS_LLM_BASE_URL", "https://progress.example.test")
    monkeypatch.setenv("PROGRESS_LLM_API_KEY", "test")
    monkeypatch.setenv("PROGRESS_LLM_MODEL", "test")
    monkeypatch.chdir(tmp_path)

    module = importlib.import_module("config.settings")

    assert Path(module.Settings.model_config["env_file"]).resolve() == Path(module.__file__).resolve().parents[1] / ".env"
    assert module.settings.progress_llm_base_url == "https://progress.example.test"
