"""Persistence-ready metadata produced after immutable extraction artifacts are stored."""

from dataclasses import dataclass

from tnpsc_book_rag.extraction.docling import ExtractedAsset
from tnpsc_book_rag.storage.models import ArtifactKey


@dataclass(frozen=True, slots=True)
class StoredAsset:
    """One extracted picture plus its canonical source and thumbnail artifacts."""

    source: ExtractedAsset
    artifact_key: ArtifactKey
    sha256: str
    thumbnail_artifact_key: ArtifactKey | None
    thumbnail_width: int | None
    thumbnail_height: int | None
