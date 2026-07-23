"""Verify extraction and web imports stay within their dependency boundaries."""

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest


@pytest.mark.parametrize("script_name", ["extract_book.py", "rechunk_book.py"])
def test_offline_scripts_do_not_require_application_or_opentelemetry(script_name: str) -> None:
    source_root = Path(__file__).parents[2] / "src"
    script_path = Path(__file__).parents[2] / "scripts" / script_name
    code = """
import runpy
import sys

class BlockApplicationDependencies:
    def find_spec(self, fullname, path=None, target=None):
        forbidden = ("opentelemetry", "tnpsc_book_rag")
        if any(fullname == name or fullname.startswith(name + ".") for name in forbidden):
            raise ModuleNotFoundError("application dependencies are not extraction dependencies")
        return None

sys.meta_path.insert(0, BlockApplicationDependencies())
sys.argv = [SCRIPT_NAME, "--help"]
try:
    runpy.run_path(SCRIPT_PATH, run_name="__main__")
except SystemExit as error:
    assert error.code == 0
assert not any(
    name == forbidden or name.startswith(forbidden + ".")
    for name in sys.modules
    for forbidden in ("opentelemetry", "tnpsc_book_rag")
)
""".replace("SCRIPT_PATH", repr(str(script_path))).replace("SCRIPT_NAME", repr(script_name))
    subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        check=True,
        cwd=source_root.parent,
        env={"PYTHONPATH": str(source_root)},
    )


def test_web_import_does_not_initialize_extraction_dependencies() -> None:
    probe = dedent(
        """
        import sys

        import tnpsc_book_rag.main

        forbidden = ("docling", "PIL", "torchvision", "cv2")
        loaded = sorted(
            name
            for name in sys.modules
            if any(name == root or name.startswith(f"{root}.") for root in forbidden)
        )
        assert not loaded, loaded
        """
    )

    subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )
