"""Typed application configuration loaded from environment variables."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import AnyHttpUrl, Field, PostgresDsn, Secret, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    """Supported application runtime environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Supported application logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    """Validated settings for the API and future ingestion worker."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        env_prefix="TNPSC_",
        extra="ignore",
        frozen=True,
    )

    environment: AppEnvironment = AppEnvironment.DEVELOPMENT
    debug: bool = False
    service_name: str = "tnpsc-book-rag-api"
    api_title: str = "TNPSC Book RAG API"
    api_version: str = "0.1.0"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    database_url: Secret[PostgresDsn] | None = None
    artifact_root: Path = Path("artifacts")
    cors_origins: tuple[AnyHttpUrl, ...] = ()
    log_level: LogLevel = LogLevel.INFO
    otel_enabled: bool = True
    otel_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    otel_traces_endpoint: AnyHttpUrl | None = None
    groq_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    mistral_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_environment_safety(self) -> Self:
        """Reject unsafe production-only setting combinations."""
        if self.environment is AppEnvironment.PRODUCTION and self.debug:
            msg = "debug mode must be disabled in production"
            raise ValueError(msg)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""
    return Settings()
