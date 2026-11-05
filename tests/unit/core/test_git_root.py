"""Finding the repository a command runs in."""

from pathlib import Path

import pytest

from noesis.core.git_root import find_git_root

pytestmark = pytest.mark.unit


def test_the_root_is_found_from_a_nested_folder(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)

    assert find_git_root(nested) == tmp_path.resolve()


def test_a_git_file_counts_as_a_root_for_worktrees(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")

    assert find_git_root(tmp_path) == tmp_path.resolve()


def test_the_nearest_root_wins(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    inner = tmp_path / "vendor" / "lib"
    (inner / ".git").mkdir(parents=True)

    assert find_git_root(inner) == inner.resolve()


def test_outside_a_repository_there_is_no_root(tmp_path: Path) -> None:
    assert find_git_root(tmp_path) is None
