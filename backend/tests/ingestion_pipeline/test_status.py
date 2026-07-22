"""Tests for ingestion-run status and durable stage policy."""

from itertools import product

import pytest

from tnpsc_book_rag.ingestion_pipeline import (
    IngestionRunStatus,
    IngestionStage,
    InvalidIngestionStageTransition,
    InvalidIngestionStatusTransition,
    can_advance_ingestion_stage,
    can_transition_ingestion_status,
    require_ingestion_stage_advance,
    require_ingestion_status_transition,
)

_ALLOWED_STATUS_TRANSITIONS = {
    (IngestionRunStatus.QUEUED, IngestionRunStatus.RUNNING),
    (IngestionRunStatus.QUEUED, IngestionRunStatus.FAILED),
    (IngestionRunStatus.RUNNING, IngestionRunStatus.SUCCEEDED),
    (IngestionRunStatus.RUNNING, IngestionRunStatus.FAILED),
    (IngestionRunStatus.FAILED, IngestionRunStatus.QUEUED),
}
_ALLOWED_STAGE_TRANSITIONS = {
    (IngestionStage.QUEUED, IngestionStage.EXTRACTION),
    (IngestionStage.EXTRACTION, IngestionStage.CHUNKING),
    (IngestionStage.CHUNKING, IngestionStage.EMBEDDING),
    (IngestionStage.EMBEDDING, IngestionStage.ACTIVATION),
}


def test_ingestion_status_transition_matrix_is_exhaustive() -> None:
    """Runs cannot skip execution states or leave successful completion."""
    for current, target in product(IngestionRunStatus, repeat=2):
        assert can_transition_ingestion_status(current, target) is (
            (current, target) in _ALLOWED_STATUS_TRANSITIONS
        )


def test_ingestion_stage_transition_matrix_is_exhaustive() -> None:
    """Durable stages move forward exactly one milestone at a time."""
    for current, target in product(IngestionStage, repeat=2):
        assert can_advance_ingestion_stage(current, target) is (
            (current, target) in _ALLOWED_STAGE_TRANSITIONS
        )


def test_ingestion_transition_guards_return_valid_targets() -> None:
    """Validated targets can be used directly by application services."""
    assert (
        require_ingestion_status_transition(
            IngestionRunStatus.QUEUED,
            IngestionRunStatus.RUNNING,
        )
        is IngestionRunStatus.RUNNING
    )
    assert (
        require_ingestion_stage_advance(IngestionStage.EXTRACTION, IngestionStage.CHUNKING)
        is IngestionStage.CHUNKING
    )


def test_invalid_ingestion_transitions_retain_typed_states() -> None:
    """Invalid status and stage changes remain suitable for stable error mapping."""
    with pytest.raises(InvalidIngestionStatusTransition) as status_error:
        require_ingestion_status_transition(
            IngestionRunStatus.SUCCEEDED,
            IngestionRunStatus.RUNNING,
        )
    with pytest.raises(InvalidIngestionStageTransition) as stage_error:
        require_ingestion_stage_advance(IngestionStage.ACTIVATION, IngestionStage.EMBEDDING)

    assert status_error.value.current is IngestionRunStatus.SUCCEEDED
    assert status_error.value.target is IngestionRunStatus.RUNNING
    assert stage_error.value.current is IngestionStage.ACTIVATION
    assert stage_error.value.target is IngestionStage.EMBEDDING
