"""Typed application configuration loaded from environment variables."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, PostgresDsn, RedisDsn, Secret, SecretStr, model_validator
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
    storage_backend: Literal["local", "s3"] = "local"
    s3_endpoint_url: AnyHttpUrl | None = None
    s3_bucket: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_region: str = "us-west-004"
    s3_prefix: str = ""
    artifact_root: Path = Path("artifacts")
    extraction_package_inbox: Path | None = None
    cors_origins: tuple[AnyHttpUrl, ...] = (
        AnyHttpUrl("http://localhost:5173"),
        AnyHttpUrl("http://127.0.0.1:5173"),
        AnyHttpUrl("http://localhost:5174"),
        AnyHttpUrl("http://127.0.0.1:5174"),
    )
    auth_enabled: bool = False
    oidc_issuer: AnyHttpUrl | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: AnyHttpUrl | None = None
    oidc_algorithms: tuple[str, ...] = ("RS256",)
    oidc_roles_claim: str = "roles"
    oidc_scopes_claim: str = "scope"
    rate_limiting_enabled: bool = False
    rate_limit_url: Secret[RedisDsn] | None = None
    rate_limit_ip_hmac_secret: SecretStr | None = None
    max_upload_bytes: int = Field(default=52_428_800, ge=1)
    max_query_characters: int = Field(default=1_000, ge=1, le=10_000)
    max_top_k: int = Field(default=50, ge=1, le=100)
    max_answer_characters_per_section: int = Field(default=8_000, ge=1)
    answer_timeout_seconds: int = Field(default=60, ge=1, le=600)
    answer_retention_seconds: int = Field(default=86_400, ge=60)
    idempotency_retention_seconds: int = Field(default=86_400, ge=86_400)
    ingestion_poll_after_seconds: int = Field(default=2, ge=1, le=60)
    worker_poll_seconds: float = Field(default=2.0, ge=0.1, le=60.0)
    docling_device: Literal["auto", "cpu", "cuda"] = "auto"
    worker_heartbeat_path: Path = Path("run/worker-heartbeat.json")
    worker_heartbeat_interval_seconds: float = Field(default=5.0, ge=0.5, le=60.0)
    worker_heartbeat_stale_after_seconds: float = Field(default=20.0, ge=1.0, le=300.0)
    thumbnail_max_edge_pixels: int = Field(default=640, ge=64, le=4_096)
    log_level: LogLevel = LogLevel.INFO
    otel_enabled: bool = True
    otel_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    otel_traces_endpoint: AnyHttpUrl | None = None
    embedding_model_identifier: str = "BAAI/bge-small-en-v1.5"
    embedding_model_revision: str = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    embedding_batch_size: int = Field(default=32, ge=1, le=256)
    embedding_device: Literal["auto", "cpu", "cuda"] = "auto"
    context_token_budget: int = Field(default=3000, ge=500, le=16000)
    llm_provider: str = "openrouter"
    llm_model: str = "nvidia/nemotron-3-nano-30b-a3b:free"
    llm_fallback_model: str = "nvidia/nemotron-nano-9b-v2:free"
    groq_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    mistral_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_environment_safety(self) -> Self:
        """Reject unsafe production-only setting combinations."""
        if self.environment is AppEnvironment.PRODUCTION and self.debug:
            msg = "debug mode must be disabled in production"
            raise ValueError(msg)
        if self.storage_backend == "s3":
            if not self.s3_endpoint_url:
                raise ValueError("s3_endpoint_url must be provided when storage_backend is s3")
            if not self.s3_bucket:
                raise ValueError("s3_bucket must be provided when storage_backend is s3")
            if not self.s3_access_key_id:
                raise ValueError("s3_access_key_id must be provided when storage_backend is s3")
            if not self.s3_secret_access_key:
                raise ValueError("s3_secret_access_key must be provided when storage_backend is s3")
        elif self.environment is AppEnvironment.PRODUCTION and not self.artifact_root.is_absolute():
            msg = "artifact root must be an absolute path in production"
            raise ValueError(msg)
        if (
            self.environment is AppEnvironment.PRODUCTION
            and self.extraction_package_inbox is not None
            and not self.extraction_package_inbox.is_absolute()
        ):
            msg = "extraction package inbox must be an absolute path in production"
            raise ValueError(msg)
        if (
            self.environment is AppEnvironment.PRODUCTION
            and not self.worker_heartbeat_path.is_absolute()
        ):
            msg = "worker heartbeat path must be absolute in production"
            raise ValueError(msg)
        if self.worker_heartbeat_stale_after_seconds <= self.worker_heartbeat_interval_seconds:
            msg = "worker heartbeat stale threshold must exceed its update interval"
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
        if self.auth_enabled:
            if self.oidc_issuer is None or self.oidc_jwks_url is None or not self.oidc_audience:
                msg = "enabled authentication requires OIDC issuer, audience, and JWKS URL"
                raise ValueError(msg)
            if self.oidc_issuer.scheme != "https" or self.oidc_jwks_url.scheme != "https":
                msg = "OIDC issuer and JWKS URL must use HTTPS"
                raise ValueError(msg)
            if not self.oidc_algorithms or any(
                algorithm not in {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
                for algorithm in self.oidc_algorithms
            ):
                msg = "OIDC algorithms must be an explicit asymmetric allowlist"
                raise ValueError(msg)
        elif self.environment is AppEnvironment.PRODUCTION:
            msg = "authentication must be enabled in production"
            raise ValueError(msg)
        if self.rate_limiting_enabled:
            if self.rate_limit_url is None:
                msg = "enabled rate limiting requires a Redis-compatible URL"
                raise ValueError(msg)
            if self.environment is AppEnvironment.PRODUCTION:
                rate_limit_url = self.rate_limit_url.get_secret_value()
                if rate_limit_url.scheme != "rediss":
                    msg = "production rate limiting requires an encrypted rediss URL"
                    raise ValueError(msg)
                secret = (
                    self.rate_limit_ip_hmac_secret.get_secret_value()
                    if self.rate_limit_ip_hmac_secret is not None
                    else ""
                )
                if len(secret) < 32:
                    msg = "production rate limiting requires a 32-character IP HMAC secret"
                    raise ValueError(msg)
        elif self.environment is AppEnvironment.PRODUCTION:
            msg = "rate limiting must be enabled in production"
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
