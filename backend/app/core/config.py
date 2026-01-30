"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # Application
    PROJECT_NAME: str = "Council-AI"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"
    API_V1_PREFIX: str = "/api/v1"

    # CORS
    CORS_ORIGINS: list[str] = ["*"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://council:council_secret@localhost:5432/council_ai"

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Synchronous database URL for Alembic migrations."""
        return self.DATABASE_URL.replace("+asyncpg", "")

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Google Cloud Platform
    GOOGLE_CLOUD_PROJECT: str = ""
    GCS_BUCKET_NAME: str = "council-data"

    # AI Services
    GEMINI_API_KEY: str = ""
    UPSTAGE_API_KEY: str = ""

    # Celery
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""

    @field_validator("CELERY_BROKER_URL", mode="before")
    @classmethod
    def set_celery_broker(cls, v: str, info: Any) -> str:
        if v:
            return v
        redis_url = info.data.get("REDIS_URL", "redis://localhost:6379/0")
        return redis_url

    @field_validator("CELERY_RESULT_BACKEND", mode="before")
    @classmethod
    def set_celery_backend(cls, v: str, info: Any) -> str:
        if v:
            return v
        redis_url = info.data.get("REDIS_URL", "redis://localhost:6379/0")
        return redis_url


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
