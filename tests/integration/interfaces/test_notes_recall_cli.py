"""`noesis notes recall` end to end: digest, bounds, exit codes and the fallback notice."""

import json
from pathlib import Path

import pytest
from tests.support.fake_obsidian_mcp import free_port

from noesis.interfaces.cli import run
from noesis.shared_kernel.domain import JsonObject

pytestmark = pytest.mark.integration

FALLBACK_NOTICE: str = "Obsidian MCP unreachable, searched files instead"
GOTCHA = "repos/demo/gotchas/cache-stampede.md"
RUN = "repos/demo/auto/runs/login-cache-rollout.md"
OTHER = "repos/other/decisions/login-cache.md"


def _note(kind: str, title: str, updated: str, body: str) -> str:
    heading: str = {"gotcha": "Symptom", "run": "Outcome", "decision": "Decision"}[kind]
    return (
        f"---\ntype: {kind}\ntitle: {title}\nupdated: {updated}\n---\n\n# {title}\n\n"
        f"## {heading}\n\n{body}\n"
    )


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder: Path = tmp_path / "vault"
    notes: dict[str, str] = {
        GOTCHA: _note("gotcha", "Cache stampede", "2026-10-20", "Login cache expires together."),
        RUN: _note("run", "Login cache rollout", "2025-01-10", "Login cache shipped."),
        OTHER: _note("decision", "Login cache elsewhere", "2026-10-20", "Login cache other repo."),
    }
    for relative, text in notes.items():
        (folder / relative).parent.mkdir(parents=True, exist_ok=True)
        (folder / relative).write_text(text, encoding="utf-8")
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


def _json(capsys: pytest.CaptureFixture[str]) -> JsonObject:
    envelope: object = json.loads(capsys.readouterr().out)
    assert isinstance(envelope, dict)
    return envelope


def _paths(envelope: JsonObject) -> list[str]:
    return [entry["path"] for entry in envelope["result"]["entries"]]  # type: ignore[index]


def test_recall_returns_a_ranked_digest_without_bodies(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "recall", "fix the login cache", "--repo", "demo", "--json"]) == 0

    envelope: JsonObject = _json(capsys)
    result: JsonObject = envelope["result"]  # type: ignore[assignment]
    assert envelope["ok"] is True
    assert _paths(envelope) == [GOTCHA, RUN]
    assert result["considered"] == 2
    assert result["omitted"] == 0
    assert result["backend"] == "filesystem"
    first: JsonObject = result["entries"][0]  # type: ignore[index]
    assert set(first) == {"kind", "title", "path", "date", "snippet"}
    assert first["kind"] == "gotcha"
    assert first["title"] == "Cache stampede"
    assert first["date"] == "2026-10-20"
    assert "notice" not in result


def test_text_output_lists_entries_with_a_path_to_read(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "recall", "login cache", "--repo", "demo"]) == 0

    text: str = capsys.readouterr().out
    assert GOTCHA in text
    assert "Cache stampede" in text
    assert "backend: filesystem" in text


def test_area_option_restricts_the_search(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["notes", "recall", "login cache", "--area", "repos/other", "--json"]) == 0

    assert _paths(_json(capsys)) == [OTHER]


def test_without_repo_or_area_the_working_repository_is_used(
    vault: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "recall", "login cache", "--json"]) == 0

    assert _paths(_json(capsys)) == [GOTCHA, RUN]


def test_without_repo_or_area_outside_a_git_repository_it_fails_typed(
    vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outside: Path = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    assert run(["notes", "recall", "login cache", "--json"]) == 2

    error: JsonObject = _json(capsys)["error"]  # type: ignore[assignment]
    assert error["code"] == "INTERFACE_002_NOT_IN_GIT_REPOSITORY"


def test_limit_and_budget_bound_the_digest(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["notes", "recall", "login cache", "--repo", "demo", "--limit", "1", "--json"]) == 0
    one: JsonObject = _json(capsys)
    assert _paths(one) == [GOTCHA]
    assert one["result"]["omitted"] == 1  # type: ignore[index]

    assert (
        run(["notes", "recall", "login cache", "--repo", "demo", "--budget-tokens", "1", "--json"])
        == 0
    )
    tiny: JsonObject = _json(capsys)
    assert _paths(tiny) == []
    assert (tiny["result"]["considered"], tiny["result"]["omitted"]) == (2, 2)  # type: ignore[index]


def test_an_empty_result_is_exit_zero_with_an_explicit_notice(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "recall", "kubernetes operator", "--repo", "demo", "--json"]) == 0
    assert _json(capsys)["result"]["entries"] == []  # type: ignore[index]

    assert run(["notes", "recall", "kubernetes operator", "--repo", "demo"]) == 0
    assert "no relevant notes" in capsys.readouterr().out


def test_a_task_without_keywords_is_a_typed_failure(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "recall", "the and of", "--repo", "demo", "--json"]) == 1

    error: JsonObject = _json(capsys)["error"]  # type: ignore[assignment]
    assert error["code"] == "NOTES_204_NO_RECALL_TERMS"


@pytest.mark.parametrize("task", ["", "  "], ids=["empty", "blank"])
def test_a_blank_task_fails_typed_with_the_json_envelope(
    task: str, vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "recall", task, "--repo", "demo", "--json"]) == 2

    error: JsonObject = _json(capsys)["error"]  # type: ignore[assignment]
    assert error["code"] == "INTERFACE_005_EMPTY_RECALL_TASK"
    assert error["next_steps"]


@pytest.mark.parametrize(
    "args",
    [
        ["login cache", "--limit", "0"],
        ["login cache", "--limit", "21"],
        ["login cache", "--budget-tokens", "-1"],
    ],
    ids=["limit-0", "limit-21", "negative-budget"],
)
def test_invalid_arguments_are_usage_errors(
    args: list[str], vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "recall", *args, "--repo", "demo"]) == 2


def test_without_a_vault_it_fails_with_vault_not_configured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "recall", "login cache", "--repo", "demo", "--json"]) == 1

    error: JsonObject = _json(capsys)["error"]  # type: ignore[assignment]
    assert error["code"] == "CORE_002_VAULT_NOT_CONFIGURED"


def test_with_obsidian_closed_recall_falls_back_to_files_and_says_so(
    vault: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_SEARCH_BACKEND", "obsidian-mcp")
    monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_URL", f"http://127.0.0.1:{free_port()}/mcp/")
    monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_TIMEOUT_SECONDS", "2")

    assert run(["notes", "recall", "login cache", "--repo", "demo", "--json"]) == 0
    envelope: JsonObject = _json(capsys)
    assert _paths(envelope) == [GOTCHA, RUN]
    assert envelope["result"]["notice"] == FALLBACK_NOTICE  # type: ignore[index]
    assert envelope["result"]["backend"] == "filesystem"  # type: ignore[index]

    assert run(["notes", "recall", "login cache", "--repo", "demo"]) == 0
    text: str = capsys.readouterr().out
    assert text.count(FALLBACK_NOTICE) == 1
