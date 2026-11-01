"""Dependency rules, enforced with import-linter (contracts live in pyproject.toml)."""

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]


def test_import_contracts_hold() -> None:
    lint_imports: str | None = shutil.which("lint-imports")
    assert lint_imports is not None, "import-linter is not installed; run `make init`"

    result: subprocess.CompletedProcess[str] = subprocess.run(
        [lint_imports], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stdout + result.stderr
