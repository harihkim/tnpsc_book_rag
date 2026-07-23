"""Persistence-ready metadata produced after immutable extraction artifacts are stored."""

from dataclasses import dataclass

from tnpsc_book_rag.artifact_storage.models import ArtifactKey
from tnpsc_book_rag.pdf_extraction.docling import ExtractedAsset


@dataclass(frozen=True, slots=True)
class StoredAsset:
    """One extracted picture plus its canonical source and thumbnail artifacts."""

    source: ExtractedAsset
    artifact_key: ArtifactKey
    sha256: str
    thumbnail_artifact_key: ArtifactKey | None
    thumbnail_width: int | None
    thumbnail_height: int | None
