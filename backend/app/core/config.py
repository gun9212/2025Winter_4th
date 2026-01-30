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
    
    # Cloud SQL Configuration
    # TODO: Add CLOUD_SQL_CONNECTION_NAME to .env when ready for production
    # Format: project:region:instance (e.g., council-ai-prod:asia-northeast3:council-db)
    CLOUD_SQL_CONNECTION_NAME: str = ""
    USE_CLOUD_SQL: bool = False  # Set to True to use Cloud SQL Connector
    
    # Database credentials (for Cloud SQL)
    POSTGRES_USER: str = "council"
    POSTGRES_PASSWORD: str = "council_secret"
    POSTGRES_DB: str = "council_ai"

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Synchronous database URL for Alembic migrations."""
        return self.DATABASE_URL.replace("+asyncpg", "")

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Google Cloud Platform
    GOOGLE_CLOUD_PROJECT: str = ""
    GCS_BUCKET_NAME: str = "council-data"
    GOOGLE_DRIVE_FOLDER_ID: str = ""

    # Vertex AI Configuration
    VERTEX_AI_LOCATION: str = "asia-northeast3"
    VERTEX_AI_EMBEDDING_MODEL: str = "text-embedding-004"
    VERTEX_AI_EMBEDDING_DIMENSION: int = 768

    # AI Services
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"  # Updated to Gemini 2.0 Flash
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

