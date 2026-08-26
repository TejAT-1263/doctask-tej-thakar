from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    superdocs_api_key: str = ""
    superdocs_base_url: str = "https://api.superdocs.app"
    database_url: str = "postgresql://doctask:doctask@localhost:5432/doctask"
    secret_key: str = "dev-secret-change-me"
    environment: str = "development"
    groq_api_key: str = ""
    groq_api_keys: str = ""
    demo_mode: bool = False
    # OpenRouter fallback — used when all Groq keys fail
    openrouter_api_key: str = ""
    # OpenAI key for text-embedding-3-small (RAG pipeline)
    # Leave blank to run without embeddings — similarity search returns empty results
    openai_api_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
