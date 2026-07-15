"""Ingestion status and stage-transition invariants."""

from collections.abc import Mapping, Set
from enum import StrEnum

from tnpsc_book_rag.ingestion.models import IngestionStage


class IngestionRunStatus(StrEnum):
    """Execution state of one auditable ingestion attempt."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


_STATUS_TRANSITIONS: Mapping[IngestionRunStatus, Set[IngestionRunStatus]] = {
    IngestionRunStatus.QUEUED: frozenset({IngestionRunStatus.RUNNING, IngestionRunStatus.FAILED}),
    IngestionRunStatus.RUNNING: frozenset(
        {IngestionRunStatus.SUCCEEDED, IngestionRunStatus.FAILED}
    ),
    IngestionRunStatus.SUCCEEDED: frozenset(),
    IngestionRunStatus.FAILED: frozenset({IngestionRunStatus.QUEUED}),
}

_STAGE_TRANSITIONS: Mapping[IngestionStage, Set[IngestionStage]] = {
    IngestionStage.QUEUED: frozenset({IngestionStage.EXTRACTION}),
    IngestionStage.EXTRACTION: frozenset({IngestionStage.CHUNKING}),
    IngestionStage.CHUNKING: frozenset({IngestionStage.EMBEDDING}),
    IngestionStage.EMBEDDING: frozenset({IngestionStage.ACTIVATION}),
    IngestionStage.ACTIVATION: frozenset(),
}


class InvalidIngestionStatusTransition(ValueError):
    """Raised when an ingestion run status change violates lifecycle policy."""

    def __init__(self, current: IngestionRunStatus, target: IngestionRunStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(
            f"ingestion status cannot transition from {current.value} to {target.value}"
        )


class InvalidIngestionStageTransition(ValueError):
    """Raised when an ingestion run skips or reverses a durable stage."""

    def __init__(self, current: IngestionStage, target: IngestionStage) -> None:
        self.current = current
        self.target = target
        super().__init__(f"ingestion stage cannot advance from {current.value} to {target.value}")


def can_transition_ingestion_status(
    current: IngestionRunStatus,
    target: IngestionRunStatus,
) -> bool:
    """Return whether the target is an immediate valid run status."""
    return target in _STATUS_TRANSITIONS[current]


def require_ingestion_status_transition(
    current: IngestionRunStatus,
    target: IngestionRunStatus,
) -> IngestionRunStatus:
    """Validate and return the next run status."""
    if not can_transition_ingestion_status(current, target):
        raise InvalidIngestionStatusTransition(current, target)
    return target


def can_advance_ingestion_stage(current: IngestionStage, target: IngestionStage) -> bool:
    """Return whether a stage is the immediate next durable milestone."""
    return target in _STAGE_TRANSITIONS[current]


def require_ingestion_stage_advance(
    current: IngestionStage,
    target: IngestionStage,
) -> IngestionStage:
    """Reject skipped, repeated, or reversed stage updates."""
    if not can_advance_ingestion_stage(current, target):
        raise InvalidIngestionStageTransition(current, target)
    return target
