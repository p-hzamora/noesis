"""The read-only filesystem adapters of interop (FR-003, FR-019, NFR-001; IMPORT_101, IMPORT_102)."""

import os
from pathlib import Path

import pytest
from tests.support.import_support import (
    N1,
    N2,
    N3,
    N4,
    N5,
    N6,
    N7,
    N8,
    N9,
    N10,
    copy_fixture_vault,
    file_snapshot,
)

from noesis.bounded_context.interop.infrastructure.outbound import (
    FilesystemFileReaderAdapter,
    FilesystemVaultReaderAdapter,
)
from noesis.exceptions import AppException

pytestmark = pytest.mark.unit

skip_as_root = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file modes")


def test_list_notes_returns_the_markdown_notes_sorted_and_nothing_else(tmp_path: Path) -> None:
    vault: Path = copy_fixture_vault(tmp_path)

    listed: list[str] = FilesystemVaultReaderAdapter(vault).list_notes()

    assert listed == sorted([N1, N2, N3, N4, N5, N6, N7, N8, N9, N10])


def test_list_notes_skips_hidden_segments_links_other_files_and_uppercase_extensions(
    tmp_path: Path,
) -> None:
    vault: Path = copy_fixture_vault(tmp_path)
    (vault / "Shout.MD").write_text("x", encoding="utf-8")
    (vault / "repos/alpha/folderlink").symlink_to("../beta", target_is_directory=True)
    (vault / "deep/.trash").mkdir(parents=True)
    (vault / "deep/.trash/gone.md").write_text("x", encoding="utf-8")

    listed: list[str] = FilesystemVaultReaderAdapter(vault).list_notes()

    assert not [path for path in listed if "folderlink" in path or ".trash" in path]
    assert ".obsidian/hidden.md" not in listed
    assert "repos/alpha/linked.md" not in listed
    assert "Shout.MD" not in listed
    assert "assets/diagram.png" not in listed and "noesis.yaml" not in listed


def test_read_returns_the_raw_bytes_and_nothing_in_the_vault_changes(tmp_path: Path) -> None:
    vault: Path = copy_fixture_vault(tmp_path)
    before = file_snapshot(vault)
    reader = FilesystemVaultReaderAdapter(vault)

    notes: list[str] = reader.list_notes()
    data: bytes = reader.read(N8)

    assert data == b"Vault readme with prose.\n"
    assert len(notes) == 10
    assert file_snapshot(vault) == before


def test_a_missing_vault_folder_raises_import_101_with_the_path(tmp_path: Path) -> None:
    missing: Path = tmp_path / "nowhere"

    with pytest.raises(AppException) as raised:
        FilesystemVaultReaderAdapter(missing).list_notes()

    assert raised.value.error_code == "IMPORT_101_VAULT_READ_FAILED"
    assert str(missing) in str(raised.value.metadata["path"])


@skip_as_root
def test_an_unreadable_note_raises_import_101_naming_it(tmp_path: Path) -> None:
    vault: Path = copy_fixture_vault(tmp_path)
    target: Path = vault / N1
    target.chmod(0)
    try:
        with pytest.raises(AppException) as raised:
            FilesystemVaultReaderAdapter(vault).read(N1)
    finally:
        target.chmod(0o644)

    assert raised.value.error_code == "IMPORT_101_VAULT_READ_FAILED"
    assert N1 in str(raised.value.metadata["path"])


def test_resolve_follows_links_and_read_returns_the_bytes(tmp_path: Path) -> None:
    real: Path = tmp_path / "real" / "design.md"
    real.parent.mkdir()
    real.write_bytes(b"# Design\n")
    link: Path = tmp_path / "link.md"
    link.symlink_to(real)
    reader = FilesystemFileReaderAdapter()

    resolved: str = reader.resolve(str(link))

    assert resolved == str(real.resolve())
    assert reader.read(resolved) == b"# Design\n"


def test_resolve_accepts_a_relative_path_and_returns_an_absolute_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "d.md").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)

    resolved: str = FilesystemFileReaderAdapter().resolve("d.md")

    assert resolved == str((tmp_path / "d.md").resolve())


@pytest.mark.parametrize("kind", ["missing", "directory"])
def test_resolve_raises_import_102_for_a_missing_path_or_a_directory(
    tmp_path: Path, kind: str
) -> None:
    target: Path = tmp_path / ("dir.md" if kind == "directory" else "missing.md")
    if kind == "directory":
        target.mkdir()

    with pytest.raises(AppException) as raised:
        FilesystemFileReaderAdapter().resolve(str(target))

    assert raised.value.error_code == "IMPORT_102_FILE_READ_FAILED"
    assert "path" in raised.value.metadata


@skip_as_root
def test_an_unreadable_file_raises_import_102(tmp_path: Path) -> None:
    secret: Path = tmp_path / "locked.md"
    secret.write_text("x", encoding="utf-8")
    secret.chmod(0)
    try:
        reader = FilesystemFileReaderAdapter()
        with pytest.raises(AppException) as raised:
            reader.read(reader.resolve(str(secret)))
    finally:
        secret.chmod(0o644)

    assert raised.value.error_code == "IMPORT_102_FILE_READ_FAILED"
