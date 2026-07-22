"""Tests for curriculum metadata carried by offline extraction manifests."""

import argparse
from collections.abc import Callable
from pathlib import Path
from runpy import run_path
from typing import cast

import pytest


def _metadata_builder() -> Callable[[argparse.Namespace], dict[str, object]]:
    script_path = Path(__file__).parents[2] / "scripts" / "extract_book.py"
    namespace = run_path(str(script_path))
    return cast(Callable[[argparse.Namespace], dict[str, object]], namespace["_book_metadata"])


def _arguments(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "title": "Tamil Nadu State Board Standard 6 Science",
        "standard": 6,
        "subject": "Science",
        "term": 1,
        "language": "english",
        "publisher": "Government of Tamil Nadu",
        "edition": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_book_metadata_contains_curriculum_identity() -> None:
    """A package manifest has every field required to register its source document."""
    metadata = _metadata_builder()(_arguments())

    assert metadata == {
        "title": "Tamil Nadu State Board Standard 6 Science",
        "standard": 6,
        "subject": "Science",
        "term": 1,
        "language": "english",
        "publisher": "Government of Tamil Nadu",
        "edition": "Term I",
    }


def test_book_metadata_rejects_blank_catalog_values() -> None:
    """Blank metadata cannot silently create an ambiguous catalog record."""
    with pytest.raises(SystemExit, match="--subject must not be blank"):
        _metadata_builder()(_arguments(subject="  "))
