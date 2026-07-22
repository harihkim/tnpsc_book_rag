"""Async-safe, allowlisted correlation metadata shared by logs and traces."""

import asyncio
import re
from collections.abc import Callable, Generator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import copy_context
from functools import partial
from typing import cast
from uuid import UUID

from structlog.contextvars import bind_contextvars, get_contextvars, reset_contextvars

_CORRELATION_FIELDS = (
    "request_id",
    "document_id",
    "ingestion_run_id",
    "stage",
)
_SAFE_CORRELATION_VALUE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def is_safe_correlation_value(value: str) -> bool:
    """Return whether a value is bounded metadata rather than free-form content."""
    return _SAFE_CORRELATION_VALUE.fullmatch(value) is not None


def get_correlation_context() -> Mapping[str, str]:
    """Return the correlation fields bound to the current async context."""
    values = get_contextvars()
    return {
        field: str(values[field]) for field in _CORRELATION_FIELDS if values.get(field) is not None
    }


@contextmanager
def correlation_context(
    *,
    request_id: str | None = None,
    document_id: UUID | str | None = None,
    ingestion_run_id: UUID | str | None = None,
    stage: str | None = None,
) -> Generator[None]:
    """Temporarily bind approved correlation fields without accepting content."""
    values = {
        "request_id": request_id,
        "document_id": document_id,
        "ingestion_run_id": ingestion_run_id,
        "stage": stage,
    }
    updates = {key: str(value) for key, value in values.items() if value is not None}
    invalid_fields = [key for key, value in updates.items() if not is_safe_correlation_value(value)]
    if invalid_fields:
        fields = ", ".join(sorted(invalid_fields))
        msg = f"correlation fields must be bounded metadata: {fields}"
        raise ValueError(msg)
    tokens = bind_contextvars(**updates)
    try:
        yield
    finally:
        reset_contextvars(**tokens)


async def run_in_thread_with_context[**P, T](
    function: Callable[P, T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Run blocking work in a thread with an explicit snapshot of current context."""
    context = copy_context()
    call = partial(context.run, function, *args, **kwargs)
    # Keep ownership local so shutdown never depends on the interpreter's default
    # executor lifecycle (which is unreliable on some Python 3.13 runtimes).
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="tnpsc-io") as executor:
        return cast(T, await asyncio.get_running_loop().run_in_executor(executor, call))
