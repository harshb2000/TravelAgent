import json
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_extra_headers: dict = {}

    serpapi_api_key: str = ""

    tavily_api_key: str = ""

    @field_validator("llm_extra_headers", mode="before")
    @classmethod
    def parse_extra_headers(cls, v: object) -> dict:
        if isinstance(v, str):
            return json.loads(v)
        return v


settings = Settings()
