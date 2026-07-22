"""Tests for the persistence-independent document lifecycle."""

from itertools import product

import pytest

from tnpsc_book_rag.textbook_catalog import (
    DocumentState,
    InvalidDocumentStateTransition,
    can_transition_document,
    require_document_transition,
)

_ALLOWED_TRANSITIONS = {
    (DocumentState.UPLOADED, DocumentState.QUEUED),
    (DocumentState.QUEUED, DocumentState.EXTRACTING),
    (DocumentState.QUEUED, DocumentState.FAILED),
    (DocumentState.EXTRACTING, DocumentState.CHUNKING),
    (DocumentState.EXTRACTING, DocumentState.FAILED),
    (DocumentState.CHUNKING, DocumentState.EMBEDDING),
    (DocumentState.CHUNKING, DocumentState.FAILED),
    (DocumentState.EMBEDDING, DocumentState.READY),
    (DocumentState.EMBEDDING, DocumentState.FAILED),
    (DocumentState.FAILED, DocumentState.QUEUED),
}


def test_document_transition_matrix_is_exhaustive() -> None:
    """Only immediate forward steps, failures, and failed retries are accepted."""
    for current, target in product(DocumentState, repeat=2):
        assert can_transition_document(current, target) is (
            (current, target) in _ALLOWED_TRANSITIONS
        )


def test_require_document_transition_returns_valid_target() -> None:
    """The guard can be composed directly into an application update."""
    assert (
        require_document_transition(DocumentState.UPLOADED, DocumentState.QUEUED)
        is DocumentState.QUEUED
    )


def test_require_document_transition_describes_invalid_change() -> None:
    """Invalid transitions retain typed current and target states for error mapping."""
    with pytest.raises(InvalidDocumentStateTransition) as captured:
        require_document_transition(DocumentState.READY, DocumentState.QUEUED)

    assert captured.value.current is DocumentState.READY
    assert captured.value.target is DocumentState.QUEUED
    assert str(captured.value) == "document cannot transition from ready to queued"
