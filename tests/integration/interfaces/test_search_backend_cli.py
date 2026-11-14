"""`NOESIS_SEARCH_BACKEND` end to end: the filesystem default and the removed `obsidian-mcp` value."""

import json
from pathlib import Path

import pytest
from tests.support.fake_claude import TTL_DECISION, success_envelope, write_fake_claude
from tests.support.notes_support import a_brief, note_file

from noesis.interfaces.cli import run
from noesis.shared_kernel.domain import JsonObject

pytestmark = pytest.mark.integration


def _note(path: str) -> str:
    return note_file(
        path,
        title="Use a TTL cache",
        origin="auto",
        body="Cache lookups for sixty seconds.",
    )


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder: Path = tmp_path / "vault"
    for relative in (
        "repos/demo/decisions/use-ttl-cache.md",
        "repos/other/decisions/use-ttl-cache.md",
    ):
        (folder / relative).parent.mkdir(parents=True)
        (folder / relative).write_text(_note(relative), encoding="utf-8")
    monkeypatch.setenv("NOESIS_VAULT_DIR", str(folder))
    monkeypatch.setenv("NOESIS_CURATOR_RETRY_SECONDS", "0")
    return folder


def _json(capsys: pytest.CaptureFixture[str]) -> JsonObject:
    envelope: object = json.loads(capsys.readouterr().out)
    assert isinstance(envelope, dict)
    return envelope


def _paths(envelope: JsonObject) -> list[str]:
    return [note["path"] for note in envelope["result"]["notes"]]  # type: ignore[index]


def _curate_fixtures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir: Path = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv(
        "NOESIS_CURATOR_CLAUDE_BIN",
        str(write_fake_claude(bin_dir, envelope=success_envelope([TTL_DECISION]))),
    )
    brief: Path = tmp_path / "brief.json"
    brief.write_text(a_brief().model_dump_json(), encoding="utf-8")
    return brief


def test_search_restricts_results_to_the_repo(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "search", "ttl", "--repo", "other", "--json"]) == 0
    assert _paths(_json(capsys)) == ["repos/other/decisions/use-ttl-cache.md"]


def test_default_search_answers_from_files_without_a_notice(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "search", "ttl cache", "--json"]) == 0
    envelope: JsonObject = _json(capsys)

    assert set(envelope) == {"ok", "result"}  # no notice key
    assert set(envelope["result"]) == {"notes", "backend"}  # type: ignore[arg-type]
    assert envelope["result"]["backend"] == "filesystem"  # type: ignore[index]


def test_list_reads_the_files(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["notes", "list", "--json"]) == 0
    assert len(_paths(_json(capsys))) == 2


def test_curate_searches_related_notes_in_files(
    vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    brief: Path = _curate_fixtures(tmp_path, monkeypatch)

    assert run(["notes", "curate", "--brief-file", str(brief), "--json"]) == 0

    result: JsonObject = _json(capsys)["result"]  # type: ignore[assignment]
    assert result["created"] + result["updated"] == ["repos/demo/decisions/use-ttl-cache.md"]  # type: ignore[operator]


@pytest.mark.parametrize("command", [["notes", "search", "ttl"], ["notes", "list"], ["doctor"]])
def test_a_removed_search_backend_fails_with_a_typed_error_before_any_io(
    command: list[str],
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NOESIS_SEARCH_BACKEND", "obsidian-mcp")

    assert run([*command, "--json"]) == 1
    captured = capsys.readouterr()
    error: JsonObject = json.loads(captured.out)["error"]

    assert error["code"] == "CORE_006_REMOVED_BACKEND"
    assert any("filesystem" in step for step in error["next_steps"])  # type: ignore[attr-defined, union-attr]
    assert error["metadata"] == {"variable": "NOESIS_SEARCH_BACKEND", "value": "obsidian-mcp"}
