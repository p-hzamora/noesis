"""Guard: nothing in the project invokes the removed `recall` and `record capture` commands.

`search` replaced `recall` and `remember` replaced `record capture`, and both old commands were
deleted. Only the `HISTORICAL` files may still mention them; a new use fails, and so does a listed
file that no longer has one.
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
        "docs/adr/0007-remember.md",  # decision record
        "docs/adr/0008-legacy-command-retirement.md",  # decision record
        "tests/integration/interfaces/test_legacy_commands_removed.py",  # asserts they are gone
        "tests/fixtures/vault_import/repos/alpha/howtos/capture.md",  # imported note text
        "tests/fixtures/vault_import_expected/B2.txt",  # expected import of that note
    }
)
"""Kept for good: they describe the past, are data, or assert the commands are gone."""


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


def test_no_legacy_command_use() -> None:
    unlisted: set[str] = legacy_users() - HISTORICAL

    assert not unlisted, (
        f"Use `noesis search` / `noesis remember` instead of the legacy commands in: {sorted(unlisted)}"
    )


def test_allow_list_has_no_stale_entry() -> None:
    stale: set[str] = HISTORICAL - legacy_users()

    assert not stale, f"No legacy command use left; remove from the allow-list: {sorted(stale)}"


def test_metric_keys_are_not_command_uses() -> None:
    assert not LEGACY_USE.search('row["recall"] for row in rows')
    assert not LEGACY_USE.search("a record captured while a rebuild runs")
