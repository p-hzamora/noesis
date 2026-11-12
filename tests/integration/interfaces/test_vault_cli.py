"""`noesis vault doctor` and `noesis vault migrate` end to end."""

import json
from pathlib import Path

import pytest
from tests.integration.notes.test_vault_migration import PLAN, build_vault

from noesis.interfaces.cli import run

pytestmark = pytest.mark.integration


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder: Path = build_vault(tmp_path / "vault")
    monkeypatch.setenv("NOESIS_VAULT_DIR", str(folder))
    return folder


@pytest.fixture
def plan_file(tmp_path: Path) -> Path:
    path: Path = tmp_path / "plan.json"
    path.write_text(json.dumps({"entries": PLAN}), encoding="utf-8")
    return path


def test_migrate_prints_counts_only_by_default_and_changes_nothing(
    vault: Path, plan_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["vault", "migrate", "--plan", str(plan_file)]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[:3] == [
        "dry run (nothing written; use --apply)",
        "plan: 4 note, 3 move, 3 keep",
        "to write: 7",
    ]
    assert "company/p/alpha/index.md" not in out  # no per-file lines without --verbose
    assert (vault / "company/p/alpha/index.md").is_file()


def test_migrate_verbose_lists_each_file_with_work(
    vault: Path, plan_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["vault", "migrate", "--plan", str(plan_file), "--verbose"]) == 0
    out = capsys.readouterr().out
    assert "move write  company/p/alpha/index.md -> repos/alpha/index.md" in out
    assert "note write  learning/t/plain.md -> learning/t/concepts/plain.md" in out


def test_migrate_apply_then_a_dry_run_has_nothing_left(
    vault: Path, plan_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["vault", "migrate", "--plan", str(plan_file), "--apply", "--json"]) == 0
    applied = json.loads(capsys.readouterr().out)["result"]
    assert applied["applied"] is True and applied["to_write"] == 7 and applied["lines"] == []
    assert (vault / "repos/alpha/index.md").is_file()

    assert run(["vault", "migrate", "--plan", str(plan_file), "--json"]) == 0
    again = json.loads(capsys.readouterr().out)["result"]
    assert again["pending"] == 0 and again["already_done"] == 7


def test_a_conflict_fails_with_its_code_and_writes_nothing(
    vault: Path, plan_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (vault / "repos/alpha").mkdir(parents=True)
    (vault / "repos/alpha/index.md").write_text("other\n", encoding="utf-8")
    assert run(["vault", "migrate", "--plan", str(plan_file), "--apply", "--json"]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "NOTES_208_MIGRATION_CONFLICT"
    assert (vault / "company/p/alpha/index.md").is_file()


def test_a_missing_plan_file_is_reported(
    vault: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["vault", "migrate", "--plan", str(tmp_path / "none.json"), "--json"]) == 1
    assert (
        json.loads(capsys.readouterr().out)["error"]["code"] == "NOTES_207_INVALID_MIGRATION_PLAN"
    )


def test_doctor_counts_and_lists_files_only_with_verbose(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (vault / "repos/alpha").mkdir(parents=True, exist_ok=True)
    (vault / "repos/alpha/index.md").write_text("# a\n", encoding="utf-8")
    args = ["vault", "doctor", "--root", "company/p"]

    assert run(args) == 0
    quiet = capsys.readouterr().out
    assert "with noesis frontmatter: 1" in quiet
    assert "projects under two roots: 1" in quiet and "alpha: company/p, repos" in quiet
    assert "without:" not in quiet

    assert run([*args, "--verbose"]) == 0
    assert "without: README.md" in capsys.readouterr().out
