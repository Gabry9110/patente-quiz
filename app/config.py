from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql://patente_quiz_app:CHANGE_ME@192.168.2.105:5432/patente_quiz"
    ollama_api_key: str = "your_ollama_api_key_here"
    ollama_model: str = "deepseek-v4-flash"
    ollama_host: str = "https://ollama.com"
    secret_key: str = "CHANGE_ME_TO_A_LONG_RANDOM_STRING"
    initial_username: str = "gabry"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        """Ensure the connection string uses the psycopg (v3) driver."""
        url = self.database_url
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        elif url.startswith("postgresql+psycopg2://"):
            url = "postgresql+psycopg://" + url[len("postgresql+psycopg2://"):]
        return url

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()