"""First-party uses of the legacy `recall` and `record capture` commands (migration guard).

`search` replaces `recall` and `remember` replaces `record capture`. Every file that still names a
legacy command is listed below; a new use fails, and so does a listed file that no longer has
one, so the lists only shrink. `PENDING_MIGRATION` must be empty before the commands are removed.
"""

import re
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.architecture

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
THIS_FILE: Final[str] = Path(__file__).resolve().relative_to(PROJECT_ROOT).as_posix()
SUFFIXES: Final[frozenset[str]] = frozenset(
    {".md", ".py", ".sh", ".txt", ".toml", ".yaml", ".yml", ".json"}
)
SKIPPED_FOLDERS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".venv",
        ".claude",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
        "graphify-out",
    }
)
LEGACY_USE: Final[re.Pattern[str]] = re.compile(
    r"noesis\s+recall\b"
    r"|\brecord\s+capture\b"
    r"|\[\s*[\"']recall[\"']\s*,"
    r"|command\(\s*[\"']recall[\"']\s*\)"
    r"|[\"']record[\"']\s*,\s*[\"']capture[\"']"
    r"|record_app\.command\(\s*[\"']capture[\"']\s*\)"
)
"""Prose and command lines, argv lists (also split across lines) and command registrations."""

HISTORICAL: Final[frozenset[str]] = frozenset(
    {
        "CHANGELOG.md",  # release history
        "tests/fixtures/vault_import/repos/alpha/howtos/capture.md",  # imported note text
        "tests/fixtures/vault_import_expected/B2.txt",  # expected import of that note
    }
)
"""Kept for good: they describe the past or are data, not invocations."""

PENDING_MIGRATION: Final[frozenset[str]] = frozenset(
    {
        "README.md",
        "docs/architecture.md",
        "docs/commands/README.md",
        "docs/commands/recall.md",
        "docs/commands/record.md",
        "docs/commands/search.md",
        "docs/guides/refactor-walkthrough.md",
        "skill_guides/noesis.md",
        "src/noesis/interfaces/cli/app.py",
        "src/noesis/interfaces/cli/commands/recall_commands.py",
        "src/noesis/interfaces/cli/commands/record_commands.py",
        "src/noesis/interfaces/cli/responses/record_response.py",
        "src/noesis/interfaces/cli/search_presentation.py",
        "tests/e2e/knowledge/test_review_processes_neo4j.py",
        "tests/e2e/retrieval/test_recall_cli.py",
        "tests/e2e/retrieval/test_search_cli.py",
        "tests/integration/interfaces/test_record_cli_neo4j.py",
        "tests/integration/interfaces/test_record_cli_offline.py",
        "tests/integration/interfaces/test_review_cli_offline.py",
        "tests/support/knowledge_cli_support.py",
        "tests/support/noesis_process_support.py",
        "tests/unit/interfaces/test_actor_resolution.py",
    }
)
"""Move to `search` / `remember`, then remove the entry."""


def legacy_users() -> set[str]:
    users: set[str] = set()
    for path in PROJECT_ROOT.rglob("*"):
        relative: Path = path.relative_to(PROJECT_ROOT)
        if (
            path.suffix not in SUFFIXES
            or SKIPPED_FOLDERS.intersection(relative.parts)
            or not path.is_file()
        ):
            continue
        try:
            text: str = path.read_text(encoding="utf-8")
        except UnicodeDecodeError, OSError:
            continue
        if LEGACY_USE.search(text):
            users.add(relative.as_posix())
    users.discard(THIS_FILE)
    return users


def test_no_new_legacy_command_use() -> None:
    unlisted: set[str] = legacy_users() - HISTORICAL - PENDING_MIGRATION

    assert not unlisted, (
        f"Use `noesis search` / `noesis remember` instead of the legacy commands in: {sorted(unlisted)}"
    )


def test_allow_list_has_no_stale_entry() -> None:
    stale: set[str] = (HISTORICAL | PENDING_MIGRATION) - legacy_users()

    assert not stale, f"No legacy command use left; remove from the allow-list: {sorted(stale)}"


def test_metric_keys_are_not_command_uses() -> None:
    assert not LEGACY_USE.search('row["recall"] for row in rows')
    assert not LEGACY_USE.search("a record captured while a rebuild runs")
