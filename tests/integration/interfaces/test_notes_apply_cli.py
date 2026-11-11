"""`noesis notes apply` end to end: writes, previews, and failures that keep the payload."""

import io
import json
from pathlib import Path

import pytest
from tests.support.git_support import add_worktree, init_repo, isolate_git

from noesis.interfaces.cli import run
from noesis.shared_kernel.domain import JsonObject

pytestmark = pytest.mark.integration

NOTE_PATH = "repos/demo/decisions/use-ttl-cache.md"
MANUAL_NOTE = (
    "---\nnoesis:\n  id: 01ARZ3NDEKTSV4RRFFQ69G5FAW\n  scope: repo:demo\n  kind: decision\n"
    "  origin: manual\n  sources: []\n  updated: 2026-01-05\n---\n\n"
    "# Use a TTL cache\n\n## Decision\n\nMine.\n"
)


def _entry(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "action": "create",
        "candidate": "ttl cache",
        "reason": "non-obvious choice",
        "kind": "decision",
        "slug": "use-ttl-cache",
        "title": "Use a TTL cache",
        "sections": [{"heading": "Decision", "body": "Keep tokens in memory."}],
    }
    return {**base, **overrides}


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder: Path = tmp_path / "vault"
    folder.mkdir()
    monkeypatch.setenv("NOESIS_VAULT_DIR", str(folder))
    monkeypatch.setenv("NOESIS_STATE_DIR", str(tmp_path / "state"))
    return folder


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git repository called `demo`, which is the working directory."""
    folder: Path = tmp_path / "demo"
    (folder / ".git").mkdir(parents=True)
    monkeypatch.chdir(folder)
    return folder


def _decisions(tmp_path: Path, *entries: dict[str, object]) -> Path:
    path: Path = tmp_path / "decisions.json"
    path.write_text(json.dumps({"decisions": list(entries) or [_entry()]}), encoding="utf-8")
    return path


def _out(capsys: pytest.CaptureFixture[str]) -> JsonObject:
    envelope: object = json.loads(capsys.readouterr().out)
    assert isinstance(envelope, dict)
    return envelope


def _failure_records(tmp_path: Path) -> list[Path]:
    folder: Path = tmp_path / "state/notes/apply-failed"
    return sorted(p for p in folder.glob("*.json") if ".payload." not in p.name)


def test_apply_writes_the_note_under_the_repository_scope(
    vault: Path, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "apply", "--decisions-file", str(_decisions(tmp_path)), "--json"]) == 0

    assert _out(capsys)["result"] == {
        "repository": "demo",
        "created": [NOTE_PATH],
        "updated": [],
        "skipped": [],
    }
    text: str = (vault / NOTE_PATH).read_text()
    assert "origin: auto" in text
    assert "sources: []" in text
    assert "session:" not in text


def test_apply_stores_the_provenance_it_is_given(vault: Path, repo: Path, tmp_path: Path) -> None:
    file: str = str(_decisions(tmp_path))

    assert (
        run(
            [
                "notes",
                "apply",
                "--decisions-file",
                file,
                "--session",
                "abcd1234ef567",
                "--commit",
                "aaa111",
                "--commit",
                "bbb222",
            ]
        )
        == 0
    )

    text: str = (vault / NOTE_PATH).read_text()
    assert "session:abcd1234\n" in text
    assert "commit:aaa111" in text
    assert "commit:bbb222" in text


def test_applying_again_updates_the_same_note(
    vault: Path, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file: str = str(_decisions(tmp_path))
    assert run(["notes", "apply", "--decisions-file", file, "--json"]) == 0
    capsys.readouterr()

    assert run(["notes", "apply", "--decisions-file", file, "--json"]) == 0

    result: JsonObject = _out(capsys)["result"]  # type: ignore[assignment]
    assert result["updated"] == [NOTE_PATH]
    assert result["created"] == []
    assert not (vault / "repos/demo/decisions/use-ttl-cache-2.md").exists()


def test_a_manual_note_wins(
    vault: Path, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manual: Path = vault / "repos/demo/decisions/use-ttl-cache.md"
    manual.parent.mkdir(parents=True)
    manual.write_text(MANUAL_NOTE, encoding="utf-8")

    assert run(["notes", "apply", "--decisions-file", str(_decisions(tmp_path)), "--json"]) == 0

    result: JsonObject = _out(capsys)["result"]  # type: ignore[assignment]
    assert result["skipped"] == [
        {"candidate": "ttl cache", "reason": "covered by repos/demo/decisions/use-ttl-cache.md"}
    ]
    assert manual.read_text() == MANUAL_NOTE
    assert not (vault / "repos/demo/decisions/use-ttl-cache-2.md").exists()


def test_apply_reads_the_decisions_from_stdin(
    vault: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"decisions": [_entry()]})))

    assert run(["notes", "apply", "--decisions-file", "-"]) == 0

    assert (vault / NOTE_PATH).is_file()


def test_dry_run_previews_without_writing_or_recording(
    vault: Path, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        run(
            ["notes", "apply", "--decisions-file", str(_decisions(tmp_path)), "--dry-run", "--json"]
        )
        == 0
    )

    assert _out(capsys)["result"] == {
        "repository": "demo",
        "created": [NOTE_PATH],
        "updated": [],
        "skipped": [],
        "dry_run": True,
    }
    assert not (vault / NOTE_PATH).exists()
    assert _failure_records(tmp_path) == []


def test_dry_run_text_says_nothing_was_written(
    vault: Path, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "apply", "--decisions-file", str(_decisions(tmp_path)), "--dry-run"]) == 0

    out: str = capsys.readouterr().out
    assert f"would create {NOTE_PATH}" in out
    assert "nothing written" in out


def test_outside_a_git_repository_apply_fails_and_writes_nothing(
    vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere: Path = tmp_path / "plain"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    file: Path = _decisions(tmp_path)

    assert run(["notes", "apply", "--decisions-file", str(file), "--json"]) == 2

    error: JsonObject = _out(capsys)["error"]  # type: ignore[assignment]
    assert error["code"] == "INTERFACE_002_NOT_IN_GIT_REPOSITORY"
    assert list(vault.iterdir()) == []
    assert _failure_records(tmp_path) == []


def test_one_malformed_entry_fails_the_whole_call_and_keeps_the_payload(
    vault: Path, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file: Path = _decisions(tmp_path, _entry(), _entry(slug="other", kind=None))

    assert run(["notes", "apply", "--decisions-file", str(file), "--json"]) == 1

    error: JsonObject = _out(capsys)["error"]  # type: ignore[assignment]
    assert error["code"] == "NOTES_203_APPLY_FAILED"
    metadata: JsonObject = error["metadata"]  # type: ignore[assignment]
    assert metadata["rejected"] == [
        {"index": 1, "reason": "create and update need a kind and a title"}
    ]
    assert not (vault / "repos").exists()
    records = _failure_records(tmp_path)
    assert len(records) == 1
    assert metadata["record_path"] == str(records[0])
    assert Path(str(metadata["payload_path"])).read_text() == file.read_text()
    assert "apply --decisions-file" in error["next_steps"][0]  # type: ignore[index]


def test_a_payload_that_is_not_json_is_kept_as_text(
    vault: Path,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("{oops"))

    assert run(["notes", "apply", "--decisions-file", "-", "--json"]) == 1

    metadata: JsonObject = _out(capsys)["error"]["metadata"]  # type: ignore[index,assignment]
    assert Path(str(metadata["payload_path"])).read_text() == "{oops"
    assert str(metadata["payload_path"]).endswith(".txt")


def test_an_unreadable_decisions_file_is_reported_and_recorded(
    vault: Path, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        run(["notes", "apply", "--decisions-file", str(tmp_path / "missing.json"), "--json"]) == 1
    )

    error: JsonObject = _out(capsys)["error"]  # type: ignore[assignment]
    assert error["code"] == "NOTES_203_APPLY_FAILED"
    assert "cannot read" in error["metadata"]["rejected"][0]["reason"]  # type: ignore[index]
    assert len(_failure_records(tmp_path)) == 1


def test_a_storage_failure_keeps_the_payload_for_a_second_try(
    vault: Path, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (vault / "repos").write_text("a file where the notes folder should be", encoding="utf-8")
    file: Path = _decisions(tmp_path)

    assert run(["notes", "apply", "--decisions-file", str(file), "--json"]) == 1

    error: JsonObject = _out(capsys)["error"]  # type: ignore[assignment]
    assert error["code"] == "NOTES_203_APPLY_FAILED"
    payload: str = str(error["metadata"]["payload_path"])  # type: ignore[index]
    assert Path(payload).read_text() == file.read_text()

    (vault / "repos").unlink()
    assert run(["notes", "apply", "--decisions-file", payload, "--json"]) == 0
    assert (vault / NOTE_PATH).is_file()


def test_apply_does_not_need_the_curator(
    vault: Path, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOESIS_CURATOR_CLAUDE_BIN", str(tmp_path / "no-such-claude"))
    monkeypatch.setenv("NOESIS_CURATOR_SYSTEM_PROMPT_FILE", str(tmp_path / "no-such-prompt.md"))

    assert run(["notes", "apply", "--decisions-file", str(_decisions(tmp_path))]) == 0


def test_apply_leaves_capture_state_alone(vault: Path, repo: Path, tmp_path: Path) -> None:
    assert run(["notes", "apply", "--decisions-file", str(_decisions(tmp_path))]) == 0

    assert not (tmp_path / "state/capture").exists()


def test_the_old_knowledge_group_no_longer_exists(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["knowledge", "list"]) == 2


def test_a_linked_worktree_writes_under_the_main_repository_scope(
    vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    isolate_git(monkeypatch)
    main = init_repo(tmp_path / "main-repo" / "demo")
    monkeypatch.chdir(add_worktree(main, tmp_path / "demo-feature", "feat/x"))

    assert run(["notes", "apply", "--decisions-file", str(_decisions(tmp_path)), "--json"]) == 0

    assert _out(capsys)["result"]["created"] == [NOTE_PATH]
    assert (vault / NOTE_PATH).is_file()
