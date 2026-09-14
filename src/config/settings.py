from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", env_file_encoding="utf-8")

    llm_base_url: str
    llm_api_key: str
    llm_model: str

    progress_llm_base_url: str
    progress_llm_api_key: str
    progress_llm_model: str

    serpapi_api_key: str = ""

    tavily_api_key: str = ""


settings = Settings()
