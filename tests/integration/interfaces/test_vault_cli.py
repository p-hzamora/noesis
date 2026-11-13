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


def test_doctor_reports_notes_outside_their_groups_folder_and_duplicates_across_roots(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (vault / "noesis.yaml").write_text(
        "groups:\n  acme: {root: company/acme, match: {repos: [alpha]}}\n", encoding="utf-8"
    )
    note = (vault / "repos/alpha/decisions").parent
    note.mkdir(parents=True, exist_ok=True)
    stray = (
        "---\nnoesis:\n  id: 01ARZ3NDEKTSV4RRFFQ69G5FAV\n  scope: repo:alpha\n"
        "  kind: decision\n  origin: auto\n  updated: 2026-01-01\n---\n# A\n"
    )
    (vault / "repos/alpha/decisions").mkdir()
    (vault / "repos/alpha/decisions/a.md").write_text(stray, encoding="utf-8")
    (vault / "company/acme/repos/alpha").mkdir(parents=True)
    (vault / "company/acme/repos/alpha/index.md").write_text("# a\n", encoding="utf-8")

    assert run(["vault", "doctor", "--verbose"]) == 0
    out = capsys.readouterr().out
    assert "misplaced notes: 1" in out and "misplaced: repos/alpha/decisions/a.md" in out
    assert "alpha: company/acme/repos, repos" in out


def _scoped_note(vault: Path, path: str, repo: str) -> None:
    target = vault / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"---\nnoesis:\n  id: 01ARZ3NDEKTSV4RRFFQ69G5FAV\n  scope: repo:{repo}\n"
        "  kind: decision\n  origin: auto\n  updated: 2026-01-01\n---\n# A\n",
        encoding="utf-8",
    )


GLOB_ONLY = "groups:\n  acme: {root: company/acme, match: {remotes: ['gitlab.com/acme/*']}}\n"


def test_doctor_infers_group_membership_from_the_group_root(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (vault / "noesis.yaml").write_text(GLOB_ONLY, encoding="utf-8")
    _scoped_note(vault, "company/acme/repos/svc/decisions/a.md", "svc")
    _scoped_note(vault, "repos/personal/decisions/b.md", "personal")

    assert run(["vault", "doctor", "--verbose"]) == 0
    out = capsys.readouterr().out
    assert "misplaced notes: 0" in out and "projects under two roots: 0" in out


def test_doctor_flags_a_repo_with_notes_under_the_group_root_and_under_repos(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (vault / "noesis.yaml").write_text(GLOB_ONLY, encoding="utf-8")
    _scoped_note(vault, "company/acme/repos/svc/decisions/a.md", "svc")
    _scoped_note(vault, "repos/svc/decisions/b.md", "svc")

    assert run(["vault", "doctor", "--verbose"]) == 0
    out = capsys.readouterr().out
    assert "misplaced notes: 1" in out and "misplaced: repos/svc/decisions/b.md" in out
    assert "svc: company/acme/repos, repos" in out


def test_doctor_flags_a_note_under_a_group_root_that_names_another_group(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (vault / "noesis.yaml").write_text(
        "groups:\n  a: {root: company/a, match: {remotes: [x]}}\n"
        "  b: {root: company/b, match: {repos: [svc]}}\n",
        encoding="utf-8",
    )
    _scoped_note(vault, "company/a/repos/svc/decisions/a.md", "svc")

    assert run(["vault", "doctor", "--verbose"]) == 0
    assert "misplaced: company/a/repos/svc/decisions/a.md" in capsys.readouterr().out
