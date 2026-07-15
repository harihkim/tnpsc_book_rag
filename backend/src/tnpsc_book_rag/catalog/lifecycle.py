"""Document lifecycle invariants independent of persistence and transport."""

from collections.abc import Mapping, Set

from tnpsc_book_rag.catalog.models import DocumentState

_DOCUMENT_TRANSITIONS: Mapping[DocumentState, Set[DocumentState]] = {
    DocumentState.UPLOADED: frozenset({DocumentState.QUEUED}),
    DocumentState.QUEUED: frozenset({DocumentState.EXTRACTING, DocumentState.FAILED}),
    DocumentState.EXTRACTING: frozenset({DocumentState.CHUNKING, DocumentState.FAILED}),
    DocumentState.CHUNKING: frozenset({DocumentState.EMBEDDING, DocumentState.FAILED}),
    DocumentState.EMBEDDING: frozenset({DocumentState.READY, DocumentState.FAILED}),
    DocumentState.READY: frozenset(),
    DocumentState.FAILED: frozenset({DocumentState.QUEUED}),
}


class InvalidDocumentStateTransition(ValueError):
    """Raised when application code attempts an unsupported lifecycle change."""

    def __init__(self, current: DocumentState, target: DocumentState) -> None:
        self.current = current
        self.target = target
        super().__init__(f"document cannot transition from {current.value} to {target.value}")


def can_transition_document(current: DocumentState, target: DocumentState) -> bool:
    """Return whether the target is an immediate valid document state."""
    return target in _DOCUMENT_TRANSITIONS[current]


def require_document_transition(current: DocumentState, target: DocumentState) -> DocumentState:
    """Validate and return a target state for use at application boundaries."""
    if not can_transition_document(current, target):
        raise InvalidDocumentStateTransition(current, target)
    return target
