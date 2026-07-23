"""Read-only discovery of verified offline extraction archives for the worker."""

from pathlib import Path

from tnpsc_book_rag.artifact_storage.keys import validate_sha256
from tnpsc_book_rag.pdf_extraction import ExtractionPackageError, verify_extraction_package
from tnpsc_book_rag.telemetry_logging import run_in_thread_with_context


class ExtractionPackageInboxError(RuntimeError):
    """Raised when a configured package inbox is missing, unsafe, or ambiguous."""


class ExtractionPackageInbox:
    """Index one immutable package per source PDF checksum.

    The inbox is a deployment input, not application-owned storage. Archives are
    verified while the index is built and are verified again by the importer before
    any artifact or database mutation.
    """

    def __init__(self, root: Path) -> None:
        self._configured_root = root.expanduser().absolute()
        self._root = self._configured_root.resolve()
        self._index: dict[str, Path] | None = None

    @property
    def root(self) -> Path:
        """Return the configured read-only inbox root."""
        return self._root

    async def find_by_source_sha256(self, source_sha256: str) -> Path | None:
        """Return the unique verified package matching an accepted source PDF."""
        normalized = validate_sha256(source_sha256)
        if self._index is None:
            self._index = await run_in_thread_with_context(self._build_index)
        return self._index.get(normalized)

    def _build_index(self) -> dict[str, Path]:
        if self._configured_root.is_symlink() or not self._root.exists() or not self._root.is_dir():
            raise ExtractionPackageInboxError(
                "configured extraction package inbox is not a regular directory"
            )

        index: dict[str, Path] = {}
        for candidate in sorted(self._root.rglob("*.zip")):
            if candidate.is_symlink() or not candidate.is_file():
                raise ExtractionPackageInboxError(
                    "extraction package inbox contains a non-regular archive"
                )
            resolved = candidate.resolve()
            if not resolved.is_relative_to(self._root):
                raise ExtractionPackageInboxError("extraction package archive escapes its inbox")
            try:
                package = verify_extraction_package(resolved)
            except ExtractionPackageError as error:
                raise ExtractionPackageInboxError(
                    "extraction package inbox contains an invalid archive"
                ) from error
            existing = index.get(package.source_sha256)
            if existing is not None and existing != resolved:
                raise ExtractionPackageInboxError(
                    "extraction package inbox contains multiple archives for one source PDF"
                )
            index[package.source_sha256] = resolved
        return index


__all__ = ["ExtractionPackageInbox", "ExtractionPackageInboxError"]
