"""Tests for async-safe correlation metadata."""

import asyncio
from uuid import UUID

import pytest

from tnpsc_book_rag.telemetry_logging import (
    correlation_context,
    get_correlation_context,
    run_in_thread_with_context,
)


def test_nested_correlation_context_is_scoped_and_restored() -> None:
    """Nested work adds fields without leaking them after completion."""
    document_id = UUID(int=1)

    assert get_correlation_context() == {}

    with correlation_context(request_id="request-1", document_id=document_id):
        assert get_correlation_context() == {
            "request_id": "request-1",
            "document_id": str(document_id),
        }

        with correlation_context(stage="extraction"):
            assert get_correlation_context()["stage"] == "extraction"

        assert "stage" not in get_correlation_context()

    assert get_correlation_context() == {}


def test_correlation_context_rejects_free_form_content() -> None:
    """Only bounded identifiers can be bound to structured correlation fields."""
    with (
        pytest.raises(ValueError, match="bounded metadata"),
        correlation_context(stage="text copied from a book"),
    ):
        pass


@pytest.mark.anyio
async def test_context_is_preserved_in_async_tasks_and_explicit_thread_helper() -> None:
    """Stage correlation survives supported task and worker-thread handoffs."""

    async def read_async_context() -> dict[str, str]:
        await asyncio.sleep(0)
        return dict(get_correlation_context())

    def read_thread_context() -> dict[str, str]:
        return dict(get_correlation_context())

    with correlation_context(request_id="request-1", stage="extraction"):
        task_context = await asyncio.create_task(read_async_context())
        thread_context = await run_in_thread_with_context(read_thread_context)

    expected = {"request_id": "request-1", "stage": "extraction"}
    assert task_context == expected
    assert thread_context == expected
