"""Regression checks for lightweight API-process import boundaries."""

import subprocess
import sys


def test_catalog_service_import_does_not_initialize_extraction_runtime() -> None:
    """Catalog/API startup must not pay the Docling and PyTorch import cost."""
    command = (
        "import sys; "
        "import tnpsc_book_rag.textbook_catalog.services; "
        "assert 'docling_core.transforms.chunker' not in sys.modules; "
        "assert 'transformers' not in sys.modules; "
        "assert 'torch' not in sys.modules"
    )

    subprocess.run(  # noqa: S603 - fixed interpreter and constant test command
        [sys.executable, "-c", command],
        check=True,
        capture_output=True,
        text=True,
    )
