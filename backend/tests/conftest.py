"""Global test safety policy for hosted model access."""

import os

import pytest

_LIVE_MODEL_FLAG = "TNPSC_ALLOW_LIVE_MODEL_TESTS"
_PROVIDER_KEYS = (
    "TNPSC_GROQ_API_KEY",
    "TNPSC_MISTRAL_API_KEY",
    "TNPSC_OPENROUTER_API_KEY",
)

if os.environ.get(_LIVE_MODEL_FLAG) != "1":
    os.environ["ALLOW_MODEL_REQUESTS"] = "false"
    for provider_key in _PROVIDER_KEYS:
        os.environ.pop(provider_key, None)


@pytest.fixture(autouse=True)
def _reset_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TNPSC_STORAGE_BACKEND", "local")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Refuse to collect opt-in provider tests unless explicitly authorized."""
    if os.environ.get(_LIVE_MODEL_FLAG) == "1":
        return
    live_tests = [item.nodeid for item in items if item.get_closest_marker("live_model")]
    if live_tests:
        formatted = "\n".join(f"- {nodeid}" for nodeid in live_tests)
        raise pytest.UsageError(f"live model tests require {_LIVE_MODEL_FLAG}=1:\n{formatted}")
