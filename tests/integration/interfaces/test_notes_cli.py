"""`noesis notes` end to end, with a fake curator executable and a temporary vault."""

import json
from pathlib import Path

import pytest
from tests.support.fake_claude import TTL_DECISION, success_envelope, write_fake_claude
from tests.support.notes_support import a_brief

from noesis.interfaces.cli import (
    run,
)
from noesis.shared_kernel.domain import (
    JsonObject,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder: Path = tmp_path / "vault"
    folder.mkdir()
    monkeypatch.setenv("NOESIS_VAULT_DIR", str(folder))
    monkeypatch.setenv("NOESIS_CURATOR_RETRY_SECONDS", "0")
    return folder


@pytest.fixture
def brief_file(tmp_path: Path) -> Path:
    path: Path = tmp_path / "brief.json"
    path.write_text(a_brief().model_dump_json(), encoding="utf-8")
    return path


def _use_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **fake: object) -> None:
    folder: Path = tmp_path / "bin"
    folder.mkdir(exist_ok=True)
    claude: Path = write_fake_claude(folder, **fake)  # type: ignore[arg-type]
    monkeypatch.setenv("NOESIS_CURATOR_CLAUDE_BIN", str(claude))


def _out(capsys: pytest.CaptureFixture[str]) -> JsonObject:
    envelope: object = json.loads(capsys.readouterr().out)
    assert isinstance(envelope, dict)
    return envelope


def test_curate_writes_auto_notes_then_search_and_list_find_them(
    vault: Path,
    brief_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _use_claude(tmp_path, monkeypatch, envelope=success_envelope([TTL_DECISION]))

    assert run(["notes", "curate", "--brief-file", str(brief_file), "--json"]) == 0
    assert _out(capsys)["result"] == {
        "repository": "demo",
        "created": ["repos/demo/auto/decisions/use-ttl-cache.md"],
        "updated": [],
        "skipped": [],
    }
    assert (vault / "repos/demo/auto/decisions/use-ttl-cache.md").is_file()

    assert run(["notes", "search", "TTL cache", "--repo", "demo", "--json"]) == 0
    assert [note["path"] for note in _out(capsys)["result"]["notes"]] == [  # type: ignore[index]
        "repos/demo/auto/decisions/use-ttl-cache.md"
    ]
    assert run(["notes", "list", "--origin", "manual"]) == 0
    assert capsys.readouterr().out.strip() == "no notes"
    assert run(["notes", "list"]) == 0
    assert "[auto decision]  Use a TTL cache" in capsys.readouterr().out


def test_curate_sends_the_configured_system_prompt_file(
    vault: Path,
    brief_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompt_file: Path = tmp_path / "curator_system.md"
    prompt_file.write_text("Keep only architecture decisions.", encoding="utf-8")
    monkeypatch.setenv("NOESIS_CURATOR_SYSTEM_PROMPT_FILE", str(prompt_file))
    _use_claude(tmp_path, monkeypatch, envelope=success_envelope([]))

    assert run(["notes", "curate", "--brief-file", str(brief_file), "--json"]) == 0

    argv: list[str] = (tmp_path / "bin/argv.txt").read_text().split("\n")
    assert argv[argv.index("--system-prompt") + 1] == "Keep only architecture decisions."


@pytest.mark.parametrize("content", [None, "  \n"], ids=["missing", "empty"])
def test_an_unusable_system_prompt_file_is_a_configuration_error(
    content: str | None,
    vault: Path,
    brief_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompt_file: Path = tmp_path / "curator_system.md"
    if content is not None:
        prompt_file.write_text(content, encoding="utf-8")
    monkeypatch.setenv("NOESIS_CURATOR_SYSTEM_PROMPT_FILE", str(prompt_file))
    _use_claude(tmp_path, monkeypatch, envelope=success_envelope([]))

    assert run(["notes", "curate", "--brief-file", str(brief_file), "--json"]) == 1

    error: JsonObject = _out(capsys)["error"]  # type: ignore[assignment]
    assert error["code"] == "CORE_005_CURATOR_PROMPT_UNREADABLE"
    assert error["metadata"] == {
        "setting": "NOESIS_CURATOR_SYSTEM_PROMPT_FILE",
        "path": str(prompt_file),
    }
    assert not (tmp_path / "bin/stdin.txt").exists()


def test_failed_curation_is_parked_listed_and_retried(
    vault: Path,
    brief_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _use_claude(tmp_path, monkeypatch, raw="not json")

    assert run(["notes", "curate", "--brief-file", str(brief_file)]) == 1
    err: str = capsys.readouterr().err
    assert "NOTES_201_CURATION_FAILED" in err
    assert "noesis notes retry" in err

    assert run(["notes", "parked", "--json"]) == 0
    ticket: str = _out(capsys)["result"]["parked"][0]["ticket"]  # type: ignore[index]

    _use_claude(tmp_path, monkeypatch, envelope=success_envelope([TTL_DECISION]))
    assert run(["notes", "retry", ticket]) == 0
    assert "1 created" in capsys.readouterr().out
    assert run(["notes", "parked"]) == 0
    assert capsys.readouterr().out.strip() == "nothing parked"


def test_invalid_brief_and_missing_vault_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "list", "--json"]) == 1
    assert _out(capsys)["error"]["code"] == "CORE_002_VAULT_NOT_CONFIGURED"  # type: ignore[index]

    monkeypatch.setenv("NOESIS_VAULT_DIR", str(tmp_path))
    bad: Path = tmp_path / "bad.json"
    bad.write_text('{"contract_version": 2}', encoding="utf-8")
    assert run(["notes", "curate", "--brief-file", str(bad), "--json"]) == 2
    assert _out(capsys)["error"]["code"] == "INTERFACE_001_INVALID_WORK_BRIEF"  # type: ignore[index]
