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
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=5, ge=0, le=20)
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    artifact_root: Path = Path("artifacts")
    cors_origins: tuple[AnyHttpUrl, ...] = ()
    max_upload_bytes: int = Field(default=52_428_800, ge=1)
    max_query_characters: int = Field(default=1_000, ge=1, le=10_000)
    max_top_k: int = Field(default=50, ge=1, le=100)
    max_answer_characters_per_section: int = Field(default=8_000, ge=1)
    answer_timeout_seconds: int = Field(default=60, ge=1, le=600)
    answer_retention_seconds: int = Field(default=86_400, ge=60)
    thumbnail_max_edge_pixels: int = Field(default=640, ge=64, le=4_096)
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
        if self.environment is AppEnvironment.PRODUCTION and not self.artifact_root.is_absolute():
            msg = "artifact root must be an absolute path in production"
            raise ValueError(msg)
        for origin in self.cors_origins:
            if origin.username is not None or origin.password is not None:
                msg = "CORS origins must not contain user information"
                raise ValueError(msg)
            if origin.query is not None or origin.fragment is not None:
                msg = "CORS origins must contain only a scheme, host, and optional port"
                raise ValueError(msg)
            if origin.path not in (None, "", "/"):
                msg = "CORS origins must contain only a scheme, host, and optional port"
                raise ValueError(msg)
        return self

    @property
    def cors_allowed_origins(self) -> tuple[str, ...]:
        """Return browser origin strings without Pydantic's URL trailing slash."""
        return tuple(str(origin).removesuffix("/") for origin in self.cors_origins)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""
    return Settings()
