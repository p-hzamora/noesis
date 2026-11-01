"""The system probe against the real file system."""

import os
import stat
from pathlib import Path

import pytest

from noesis.diagnostics.infrastructure.outbound.probes import SystemEnvironmentProbeAdapter

pytestmark = pytest.mark.integration


def test_files_and_folders_are_told_apart(tmp_path: Path) -> None:
    probe = SystemEnvironmentProbeAdapter()
    file: Path = tmp_path / "a.txt"
    file.write_text("x", encoding="utf-8")

    assert probe.exists(tmp_path) and probe.exists(file) and not probe.exists(tmp_path / "no")
    assert probe.is_file(file) and not probe.is_file(tmp_path)
    assert probe.is_writable_folder(tmp_path) and not probe.is_writable_folder(file)
    assert list(tmp_path.iterdir()) == [file]  # the writability test leaves nothing behind


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_a_read_only_folder_is_not_writable(tmp_path: Path) -> None:
    folder: Path = tmp_path / "ro"
    folder.mkdir()
    folder.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        assert not SystemEnvironmentProbeAdapter().is_writable_folder(folder)
    finally:
        folder.chmod(stat.S_IRWXU)


def test_executables_are_found_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool: Path = tmp_path / "mytool"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    probe = SystemEnvironmentProbeAdapter()

    assert probe.find_executable("mytool") == str(tool)
    assert probe.find_executable("nothing-here") is None
