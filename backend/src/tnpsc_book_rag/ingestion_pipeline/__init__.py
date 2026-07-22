"""Ingestion run types and lifecycle policy with lazy service exports."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tnpsc_book_rag.ingestion_pipeline.models import IngestionStage
    from tnpsc_book_rag.ingestion_pipeline.package_import import ExtractionPackageImportService
    from tnpsc_book_rag.ingestion_pipeline.status import (
        IngestionRunStatus,
        InvalidIngestionStageTransition,
        InvalidIngestionStatusTransition,
        can_advance_ingestion_stage,
        can_transition_ingestion_status,
        require_ingestion_stage_advance,
        require_ingestion_status_transition,
    )

_EXPORTS = {
    "ExtractionPackageImportService": (
        "tnpsc_book_rag.ingestion_pipeline.package_import",
        "ExtractionPackageImportService",
    ),
    "IngestionRunStatus": ("tnpsc_book_rag.ingestion_pipeline.status", "IngestionRunStatus"),
    "IngestionStage": ("tnpsc_book_rag.ingestion_pipeline.models", "IngestionStage"),
    "InvalidIngestionStageTransition": (
        "tnpsc_book_rag.ingestion_pipeline.status",
        "InvalidIngestionStageTransition",
    ),
    "InvalidIngestionStatusTransition": (
        "tnpsc_book_rag.ingestion_pipeline.status",
        "InvalidIngestionStatusTransition",
    ),
    "can_advance_ingestion_stage": (
        "tnpsc_book_rag.ingestion_pipeline.status",
        "can_advance_ingestion_stage",
    ),
    "can_transition_ingestion_status": (
        "tnpsc_book_rag.ingestion_pipeline.status",
        "can_transition_ingestion_status",
    ),
    "require_ingestion_stage_advance": (
        "tnpsc_book_rag.ingestion_pipeline.status",
        "require_ingestion_stage_advance",
    ),
    "require_ingestion_status_transition": (
        "tnpsc_book_rag.ingestion_pipeline.status",
        "require_ingestion_status_transition",
    ),
}

__all__ = [
    "ExtractionPackageImportService",
    "IngestionRunStatus",
    "IngestionStage",
    "InvalidIngestionStageTransition",
    "InvalidIngestionStatusTransition",
    "can_advance_ingestion_stage",
    "can_transition_ingestion_status",
    "require_ingestion_stage_advance",
    "require_ingestion_status_transition",
]


def __getattr__(name: str) -> object:
    """Resolve package-level exports without loading the package importer eagerly."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
