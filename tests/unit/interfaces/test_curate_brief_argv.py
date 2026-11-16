"""The composition root builds the detached child's argv; Capture names no consumer (D-012)."""

import sys
from pathlib import Path

import pytest

from noesis.core import load_environment
from noesis.interfaces.cli.bootstrap import curate_brief_argv, curator_command

pytestmark = pytest.mark.unit


def test_the_argv_is_the_reentry_command_plus_curate_brief_for_the_file(tmp_path: Path) -> None:
    environment = load_environment(tmp_path / "noesis.env")
    brief = tmp_path / "briefs" / "b.json"

    argv = curate_brief_argv(environment, brief)

    assert argv == [
        sys.executable,
        "-m",
        "noesis",
        "--env-file",
        str(tmp_path / "noesis.env"),
        "curate",
        "brief",
        "--brief-file",
        str(brief),
        "--json",
    ]
    assert argv[: len(curator_command(environment))] == curator_command(environment)


def test_capture_never_names_the_consumers_command() -> None:
    capture = Path(__file__).parents[3] / "src/noesis/bounded_context/capture"

    offenders = [
        path
        for path in capture.rglob("*.py")
        if '"curate"' in path.read_text(encoding="utf-8")
        or '"notes"' in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
