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


def test_api_port_must_be_valid() -> None:
    """Invalid TCP port numbers fail during settings construction."""
    with pytest.raises(ValidationError):
        Settings.model_validate({"api_port": 0})


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
