"""Verify the offline extraction runtime does not import application observability."""

import subprocess
import sys
from pathlib import Path


def test_extraction_script_does_not_require_opentelemetry() -> None:
    source_root = Path(__file__).parents[2] / "src"
    script_path = Path(__file__).parents[2] / "scripts" / "extract_book.py"
    code = """
import runpy
import sys

class BlockOpenTelemetry:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "opentelemetry" or fullname.startswith("opentelemetry."):
            raise ModuleNotFoundError("OpenTelemetry is not an extraction dependency")
        return None

sys.meta_path.insert(0, BlockOpenTelemetry())
sys.argv = ["extract_book.py", "--help"]
try:
    runpy.run_path(SCRIPT_PATH, run_name="__main__")
except SystemExit as error:
    assert error.code == 0
assert not any(name == "opentelemetry" or name.startswith("opentelemetry.") for name in sys.modules)
""".replace("SCRIPT_PATH", repr(str(script_path)))
    subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        check=True,
        cwd=source_root.parent,
        env={"PYTHONPATH": str(source_root)},
    )
