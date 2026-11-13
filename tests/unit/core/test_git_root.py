"""Finding the repository a command runs in."""

from pathlib import Path

import pytest
from tests.support.git_support import add_worktree, git, init_repo, isolate_git

from noesis.core.git_root import (
    canonical_remote,
    find_common_dir,
    find_git_root,
    find_main_repository,
    repository_name,
    repository_remote,
)

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


# --- repository identity across main checkouts, linked worktrees, bare repos and submodules ---


@pytest.fixture
def git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_git(monkeypatch)


def test_a_main_checkout_is_its_own_main_repository(tmp_path: Path, git_env: None) -> None:
    main = init_repo(tmp_path / "billing")

    assert find_common_dir(main) == main / ".git"
    assert find_main_repository(main) == main
    assert repository_name(main / ".git") == "billing"


def test_a_linked_worktree_resolves_to_the_main_checkout(tmp_path: Path, git_env: None) -> None:
    main = init_repo(tmp_path / "billing")
    linked = add_worktree(main, tmp_path / "billing-feature", "feat/x")
    nested = linked / "pkg"
    nested.mkdir()

    assert find_common_dir(nested) == main / ".git"
    assert find_main_repository(nested) == main
    assert repository_name(find_common_dir(linked) or linked) == "billing"


def test_a_bare_repository_is_its_own_identity(tmp_path: Path, git_env: None) -> None:
    bare = init_repo(tmp_path / "origin.git", bare=True)

    assert find_common_dir(bare) == bare
    assert find_main_repository(bare) == bare
    assert repository_name(bare) == "origin.git"


def test_a_submodule_is_named_after_its_module_not_the_parent(
    tmp_path: Path, git_env: None
) -> None:
    inner = init_repo(tmp_path / "inner")
    outer = init_repo(tmp_path / "outer")
    git(outer, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(inner), "lib")

    common = find_common_dir(outer / "lib")

    assert common == outer / ".git" / "modules" / "lib"
    assert repository_name(common) == "lib"
    assert find_main_repository(outer / "lib") == outer / "lib"


def test_outside_any_repository_there_is_no_identity(tmp_path: Path) -> None:
    assert find_common_dir(tmp_path) is None
    assert find_main_repository(tmp_path) is None


@pytest.mark.parametrize(
    ("common_dir", "expected"),
    [
        ("/w/billing/.git", "billing"),
        ("/w/billing/.git/modules/lib", "lib"),
        ("/srv/origin.git", "origin.git"),
    ],
)
def test_the_naming_rule(common_dir: str, expected: str) -> None:
    assert repository_name(Path(common_dir)) == expected


@pytest.mark.parametrize(
    "url",
    [
        "git@gitlab.com:grupost/dafne/api.git",
        "https://gitlab.com/grupost/dafne/api.git",
        "https://user:token@gitlab.com/grupost/dafne/api",
        "ssh://git@gitlab.com:2222/grupost/dafne/api.git",
        "gitlab.com:grupost/dafne/api.git",
    ],
)
def test_every_spelling_of_a_remote_has_one_canonical_form(url: str) -> None:
    assert canonical_remote(url) == "gitlab.com/grupost/dafne/api"


def test_the_remote_is_read_from_the_git_config_preferring_origin(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[core]\n\turl = nope\n[remote "backup"]\n\turl = git@a.com:x/y.git\n'
        '[remote "origin"]\n\turl = git@gitlab.com:grupost/api.git\n\tfetch = +refs/*\n'
    )
    assert repository_remote(git_dir) == "gitlab.com/grupost/api"


def test_no_remote_or_no_config_reads_as_none(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert repository_remote(tmp_path / ".git") is None
    (tmp_path / ".git" / "config").write_text("[core]\n\tbare = false\n")
    assert repository_remote(tmp_path / ".git") is None
