"""Tests for typed application settings."""

from pathlib import Path
from secrets import token_hex

import pytest
from pydantic import SecretStr, ValidationError

from tnpsc_book_rag.config import AppEnvironment, LogLevel, Settings


def test_settings_load_prefixed_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """TNPSC-prefixed variables are parsed into their declared types."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TNPSC_ENVIRONMENT", "test")
    monkeypatch.setenv("TNPSC_API_PORT", "8100")
    monkeypatch.setenv("TNPSC_CORS_ORIGINS", '["http://localhost:5173"]')
    monkeypatch.setenv("TNPSC_LOG_LEVEL", "WARNING")

    settings = Settings()

    assert settings.environment is AppEnvironment.TEST
    assert settings.api_port == 8100
    assert tuple(str(origin) for origin in settings.cors_origins) == ("http://localhost:5173/",)
    assert settings.cors_allowed_origins == ("http://localhost:5173",)
    assert settings.log_level is LogLevel.WARNING


def test_empty_provider_key_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Empty example-file values do not become usable credentials."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TNPSC_GROQ_API_KEY", "")

    settings = Settings()

    assert settings.groq_api_key is None


def test_production_rejects_debug_mode() -> None:
    """Production configuration cannot enable framework debug behavior."""
    with pytest.raises(ValidationError, match="debug mode must be disabled"):
        Settings.model_validate({"environment": AppEnvironment.PRODUCTION, "debug": True})


def test_production_requires_authentication_and_rate_limiting(tmp_path: Path) -> None:
    """A production API cannot silently expose protected routes without enforcement."""
    production_paths = {
        "environment": AppEnvironment.PRODUCTION,
        "debug": False,
        "artifact_root": tmp_path,
        "extraction_package_inbox": None,
        "worker_heartbeat_path": tmp_path / "worker.json",
    }
    with pytest.raises(ValidationError, match="authentication must be enabled"):
        Settings.model_validate(production_paths)

    with pytest.raises(ValidationError, match="rate limiting must be enabled"):
        Settings.model_validate(
            {
                **production_paths,
                "auth_enabled": True,
                "oidc_issuer": "https://identity.example.com/",
                "oidc_audience": "tnpsc-api",
                "oidc_jwks_url": "https://identity.example.com/.well-known/jwks.json",
            }
        )


def test_production_security_requires_https_and_encrypted_shared_state(tmp_path: Path) -> None:
    """Production identity metadata and enforcement state must use encrypted transport."""
    base = {
        "environment": AppEnvironment.PRODUCTION,
        "debug": False,
        "artifact_root": tmp_path,
        "extraction_package_inbox": None,
        "worker_heartbeat_path": tmp_path / "worker.json",
        "auth_enabled": True,
        "oidc_issuer": "https://identity.example.com/",
        "oidc_audience": "tnpsc-api",
        "oidc_jwks_url": "https://identity.example.com/.well-known/jwks.json",
        "rate_limiting_enabled": True,
        "rate_limit_ip_hmac_secret": "a" * 32,
    }
    with pytest.raises(ValidationError, match="encrypted rediss URL"):
        Settings.model_validate({**base, "rate_limit_url": "redis://localhost:6379/0"})

    settings = Settings.model_validate(
        {**base, "rate_limit_url": "rediss://user:secret@cache.example.com:6379/0"}
    )
    assert settings.auth_enabled is True
    assert settings.rate_limiting_enabled is True


def test_production_requires_absolute_artifact_root() -> None:
    """Production storage cannot silently move when the process working directory changes."""
    with pytest.raises(ValidationError, match="artifact root must be an absolute path"):
        Settings.model_validate(
            {
                "environment": AppEnvironment.PRODUCTION,
                "debug": False,
                "artifact_root": "relative-artifacts",
            }
        )


def test_api_port_must_be_valid() -> None:
    """Invalid TCP port numbers fail during settings construction."""
    with pytest.raises(ValidationError):
        Settings.model_validate({"api_port": 0})


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.com/path",
        "https://example.com?query=yes",
        "https://example.com#fragment",
        "https://user@example.com",
    ],
)
def test_cors_origins_reject_non_origin_urls(origin: str) -> None:
    """CORS configuration accepts origins, not arbitrary URLs."""
    with pytest.raises(ValidationError, match="CORS origins"):
        Settings.model_validate({"cors_origins": [origin]})


def test_api_client_limits_have_frozen_defaults() -> None:
    """Published capability limits and server enforcement share one source."""
    settings = Settings()

    assert settings.max_upload_bytes == 52_428_800
    assert settings.max_query_characters == 1_000
    assert settings.max_top_k == 50
    assert settings.max_answer_characters_per_section == 8_000
    assert settings.answer_timeout_seconds == 60
    assert settings.answer_retention_seconds == 86_400
    assert settings.idempotency_retention_seconds == 86_400
    assert settings.ingestion_poll_after_seconds == 2
    assert settings.thumbnail_max_edge_pixels == 640


def test_idempotency_and_worker_health_windows_are_safely_bounded() -> None:
    """Replay guarantees and heartbeat health cannot be configured below safe bounds."""
    with pytest.raises(ValidationError):
        Settings.model_validate({"idempotency_retention_seconds": 3_600})
    with pytest.raises(ValidationError, match="stale threshold"):
        Settings.model_validate(
            {
                "worker_heartbeat_interval_seconds": 10,
                "worker_heartbeat_stale_after_seconds": 10,
            }
        )


def test_production_requires_absolute_worker_heartbeat_path(tmp_path: Path) -> None:
    """A production worker health file cannot move with its working directory."""
    with pytest.raises(ValidationError, match="heartbeat path must be absolute"):
        Settings.model_validate(
            {
                "environment": AppEnvironment.PRODUCTION,
                "debug": False,
                "artifact_root": tmp_path,
                "extraction_package_inbox": tmp_path / "inbox",
                "worker_heartbeat_path": "relative-heartbeat.json",
            }
        )


def test_production_requires_absolute_extraction_package_inbox(tmp_path: Path) -> None:
    """A production package handoff cannot silently move with the working directory."""
    with pytest.raises(ValidationError, match="package inbox must be an absolute path"):
        Settings.model_validate(
            {
                "environment": AppEnvironment.PRODUCTION,
                "debug": False,
                "artifact_root": tmp_path,
                "worker_heartbeat_path": tmp_path / "worker.json",
                "extraction_package_inbox": "relative-inbox",
            }
        )


def test_provider_secrets_are_masked_when_serialized() -> None:
    """Pydantic serialization must not reveal provider credentials."""
    raw_secret = token_hex(16)
    settings = Settings.model_validate({"groq_api_key": SecretStr(raw_secret)})

    assert raw_secret not in settings.model_dump_json()


def test_database_url_is_validated_and_masked() -> None:
    """Database credentials remain secret without sacrificing DSN validation."""
    raw_database_url = f"postgresql://user:{token_hex(16)}@localhost:5432/tnpsc"
    settings = Settings.model_validate({"database_url": raw_database_url})

    assert raw_database_url not in settings.model_dump_json()

    with pytest.raises(ValidationError):
        Settings.model_validate({"database_url": "https://localhost/not-postgres"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_pool_size", 0),
        ("database_max_overflow", -1),
        ("database_connect_timeout_seconds", 0),
    ],
)
def test_database_resource_limits_are_bounded(field: str, value: int) -> None:
    """Unsafe database pool and timeout values fail during settings validation."""
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})


@pytest.mark.parametrize("sample_ratio", [-0.1, 1.1])
def test_telemetry_sample_ratio_is_bounded(sample_ratio: float) -> None:
    """Invalid trace sampling ratios fail during settings validation."""
    with pytest.raises(ValidationError):
        Settings.model_validate({"otel_sample_ratio": sample_ratio})
