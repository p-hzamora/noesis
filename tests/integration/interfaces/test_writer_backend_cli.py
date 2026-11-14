"""`NOESIS_WRITER_BACKEND` end to end: the filesystem default and the removed `mcp` value."""

import json
from pathlib import Path

import pytest
from tests.support.fake_claude import TTL_DECISION, success_envelope, write_fake_claude
from tests.support.notes_support import a_brief

from noesis.interfaces.cli import run
from noesis.shared_kernel.domain import JsonObject

pytestmark = pytest.mark.integration

TTL_PATH: str = "repos/demo/decisions/use-ttl-cache.md"


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The local vault (`NOESIS_VAULT_DIR`): where the filesystem writer and file search look."""
    folder: Path = tmp_path / "vault"
    folder.mkdir()
    monkeypatch.setenv("NOESIS_VAULT_DIR", str(folder))
    monkeypatch.setenv("NOESIS_CURATOR_RETRY_SECONDS", "0")
    return folder


def _json(capsys: pytest.CaptureFixture[str]) -> JsonObject:
    envelope: object = json.loads(capsys.readouterr().out)
    assert isinstance(envelope, dict)
    return envelope


def _error(envelope: JsonObject) -> JsonObject:
    return envelope["error"]  # type: ignore[return-value]


def _use_curator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *decisions: JsonObject) -> Path:
    """Install the fake `claude` answering `decisions`; returns the brief file to curate."""
    folder: Path = tmp_path / "bin"
    folder.mkdir(exist_ok=True)
    monkeypatch.setenv(
        "NOESIS_CURATOR_CLAUDE_BIN",
        str(write_fake_claude(folder, envelope=success_envelope(list(decisions)))),
    )
    brief: Path = tmp_path / "brief.json"
    brief.write_text(a_brief().model_dump_json(), encoding="utf-8")
    return brief


def _curate(brief: Path, *extra: str) -> int:
    return run(["notes", "curate", "--brief-file", str(brief), "--json", *extra])


def test_default_writer_writes_files_under_the_vault(
    vault: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    brief: Path = _use_curator(tmp_path, monkeypatch, TTL_DECISION)

    assert _curate(brief) == 0

    assert _json(capsys)["result"]["created"] == [TTL_PATH]  # type: ignore[index]
    assert (vault / TTL_PATH).is_file()


def test_the_filesystem_writer_needs_a_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_CURATOR_RETRY_SECONDS", "0")  # no NOESIS_VAULT_DIR at all
    brief: Path = _use_curator(tmp_path, monkeypatch, TTL_DECISION)

    assert _curate(brief) == 1
    assert _error(_json(capsys))["code"] == "CORE_002_VAULT_NOT_CONFIGURED"
    assert not (tmp_path / "bin/stdin.txt").exists()  # failed before the curator ran


def test_a_removed_writer_backend_fails_with_a_typed_error_before_any_io(
    vault: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    brief: Path = _use_curator(tmp_path, monkeypatch, TTL_DECISION)
    monkeypatch.setenv("NOESIS_WRITER_BACKEND", "mcp")

    assert _curate(brief) == 1
    error: JsonObject = _error(_json(capsys))

    assert error["code"] == "CORE_006_REMOVED_BACKEND"
    assert any("filesystem" in step for step in error["next_steps"])  # type: ignore[attr-defined, union-attr]
    assert error["metadata"] == {"variable": "NOESIS_WRITER_BACKEND", "value": "mcp"}
    assert not (tmp_path / "bin/stdin.txt").exists()  # the curator never ran
    assert not (vault / TTL_PATH).exists()


def test_a_storage_failure_on_the_default_backend_parks_the_brief(
    vault: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (vault / "repos").write_text("a file where the notes folder should be", encoding="utf-8")
    brief: Path = _use_curator(tmp_path, monkeypatch, TTL_DECISION)

    assert _curate(brief) == 1
    error: JsonObject = _error(_json(capsys))
    assert error["code"] == "NOTES_201_CURATION_FAILED"
    ticket: str = error["metadata"]["ticket"]  # type: ignore[index]
    assert f"Fix the cause, then run `noesis notes retry {ticket}`." in error["next_steps"]  # type: ignore[operator]

    (vault / "repos").unlink()  # storage is fixed
    assert run(["notes", "retry", ticket, "--json"]) == 0
    assert _json(capsys)["result"]["created"] == [TTL_PATH]  # type: ignore[index]
    assert (vault / TTL_PATH).is_file()


def test_a_storage_failure_without_parking_keeps_the_storage_error_code(
    vault: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (vault / "repos").write_text("a file where the notes folder should be", encoding="utf-8")
    brief: Path = _use_curator(tmp_path, monkeypatch, TTL_DECISION)

    assert _curate(brief, "--no-park") == 1
    assert _error(_json(capsys))["code"] == "NOTES_102_NOTE_STORAGE_FAILED"
    assert run(["notes", "parked", "--json"]) == 0
    assert _json(capsys)["result"]["parked"] == []  # type: ignore[index]


def _checks(capsys: pytest.CaptureFixture[str]) -> dict[str, JsonObject]:
    envelope: JsonObject = _json(capsys)
    return {check["name"]: check for check in envelope["result"]["checks"]}  # type: ignore[index]


@pytest.fixture
def curator_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder: Path = tmp_path / "doctor-bin"
    folder.mkdir()
    for name in ("claude", "git"):
        (folder / name).write_text("#!/bin/sh\n", encoding="utf-8")
        (folder / name).chmod(0o755)
    monkeypatch.setenv("PATH", str(folder))


@pytest.mark.usefixtures("curator_on_path")
def test_doctor_reports_the_filesystem_writer_and_no_obsidian_check(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(["doctor", "--json"])
    checks: dict[str, JsonObject] = _checks(capsys)

    assert checks["writer"]["ok"] is True
    assert str(vault) in checks["writer"]["detail"]  # type: ignore[operator]
    assert not [name for name in checks if "obsidian" in name or "mcp" in name]
    assert "obsidian" not in json.dumps(checks).lower()
