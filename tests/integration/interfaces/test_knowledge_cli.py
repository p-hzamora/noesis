"""`noesis knowledge` end to end, with a fake curator executable and a temporary vault."""

import json
from pathlib import Path

import pytest
from tests.support.fake_claude import TTL_DECISION, success_envelope, write_fake_claude
from tests.support.knowledge_support import a_brief

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

    assert run(["knowledge", "curate", "--brief-file", str(brief_file), "--json"]) == 0
    assert _out(capsys)["result"] == {
        "repository": "demo",
        "created": ["repos/demo/auto/decisions/use-ttl-cache.md"],
        "updated": [],
        "skipped": [],
    }
    assert (vault / "repos/demo/auto/decisions/use-ttl-cache.md").is_file()

    assert run(["knowledge", "search", "TTL cache", "--repo", "demo", "--json"]) == 0
    assert [note["path"] for note in _out(capsys)["result"]["notes"]] == [  # type: ignore[index]
        "repos/demo/auto/decisions/use-ttl-cache.md"
    ]
    assert run(["knowledge", "list", "--origin", "manual"]) == 0
    assert capsys.readouterr().out.strip() == "no notes"
    assert run(["knowledge", "list"]) == 0
    assert "[auto decision]  Use a TTL cache" in capsys.readouterr().out


def test_failed_curation_is_parked_listed_and_retried(
    vault: Path,
    brief_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _use_claude(tmp_path, monkeypatch, raw="not json")

    assert run(["knowledge", "curate", "--brief-file", str(brief_file)]) == 1
    err: str = capsys.readouterr().err
    assert "KNOWLEDGE_201_CURATION_FAILED" in err
    assert "noesis knowledge retry" in err

    assert run(["knowledge", "parked", "--json"]) == 0
    ticket: str = _out(capsys)["result"]["parked"][0]["ticket"]  # type: ignore[index]

    _use_claude(tmp_path, monkeypatch, envelope=success_envelope([TTL_DECISION]))
    assert run(["knowledge", "retry", ticket]) == 0
    assert "1 created" in capsys.readouterr().out
    assert run(["knowledge", "parked"]) == 0
    assert capsys.readouterr().out.strip() == "nothing parked"


def test_invalid_brief_and_missing_vault_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["knowledge", "list", "--json"]) == 1
    assert _out(capsys)["error"]["code"] == "CORE_002_VAULT_NOT_CONFIGURED"  # type: ignore[index]

    monkeypatch.setenv("NOESIS_VAULT_DIR", str(tmp_path))
    bad: Path = tmp_path / "bad.json"
    bad.write_text('{"contract_version": 2}', encoding="utf-8")
    assert run(["knowledge", "curate", "--brief-file", str(bad), "--json"]) == 2
    assert _out(capsys)["error"]["code"] == "INTERFACE_001_INVALID_WORK_BRIEF"  # type: ignore[index]
