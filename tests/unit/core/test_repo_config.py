"""Repository config: `.noesis-config` discovery, parsing and profile resolution."""

from pathlib import Path

import pytest
from tests.support.git_support import add_worktree, init_repo, isolate_git

from noesis.core.repo_config import (
    find_repo_config,
    profile_env_file,
    read_repo_config,
    resolve_env_file,
)
from noesis.exceptions import InvalidConfigurationError


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home: Path = tmp_path / "xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    return home


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root: Path = tmp_path / "work" / "billing"
    (root / ".git").mkdir(parents=True)
    return root


def test_finds_config_at_repo_root(repo: Path) -> None:
    (repo / ".noesis-config").write_text("profile = fast\n", encoding="utf-8")

    assert find_repo_config(repo) == repo / ".noesis-config"


def test_finds_config_from_a_subdirectory(repo: Path) -> None:
    (repo / ".noesis-config").write_text("profile = fast\n", encoding="utf-8")
    sub: Path = repo / "src" / "pkg"
    sub.mkdir(parents=True)

    assert find_repo_config(sub) == repo / ".noesis-config"


def test_stops_at_git_root_and_ignores_parent_repo_config(tmp_path: Path) -> None:
    (tmp_path / ".noesis-config").write_text("profile = outer\n", encoding="utf-8")
    inner: Path = tmp_path / "inner"
    (inner / ".git").mkdir(parents=True)

    assert find_repo_config(inner) is None


def test_returns_none_outside_any_config(repo: Path) -> None:
    assert find_repo_config(repo) is None


def test_reads_profile(repo: Path) -> None:
    path: Path = repo / ".noesis-config"
    path.write_text("# billing repo\n\nprofile = gpt-fast\n", encoding="utf-8")

    config = read_repo_config(path)

    assert config.profile == "gpt-fast"
    assert config.repo_name == "billing"


@pytest.mark.parametrize(
    "content",
    [
        "NOESIS_CURATOR_CLAUDE_BIN = /tmp/evil\n",
        "profile = ../escape\n",
        "profile =\n",
        "profile = a/b\n",
        "just-a-line\n",
    ],
)
def test_rejects_unsafe_or_unknown_content(repo: Path, content: str) -> None:
    path: Path = repo / ".noesis-config"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(InvalidConfigurationError):
        read_repo_config(path)


def test_profile_lives_in_per_repo_folder(repo: Path, config_home: Path) -> None:
    config = read_repo_config(_write(repo, "profile = fast\n"))

    assert profile_env_file(config) == config_home / "noesis" / "profiles" / "billing" / "fast.env"


def test_explicit_env_file_wins_over_repo_config(repo: Path, config_home: Path) -> None:
    _write(repo, "profile = fast\n")
    explicit: Path = repo / "custom.env"

    assert resolve_env_file(explicit, repo) == explicit


def test_repo_profile_used_when_no_explicit_file(repo: Path, config_home: Path) -> None:
    _write(repo, "profile = fast\n")

    assert resolve_env_file(None, repo) == (
        config_home / "noesis" / "profiles" / "billing" / "fast.env"
    )


def test_no_repo_config_falls_back_to_default(repo: Path) -> None:
    assert resolve_env_file(None, repo) is None


def _write(repo: Path, content: str) -> Path:
    path: Path = repo / ".noesis-config"
    path.write_text(content, encoding="utf-8")
    return path


# --- linked worktrees ---


@pytest.fixture
def worktree_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    isolate_git(monkeypatch)
    main = init_repo(tmp_path / "work" / "billing")
    linked = add_worktree(main, tmp_path / "work" / "billing-feature", "feat/x")
    return main, linked


def test_a_worktree_without_its_own_config_reads_the_main_worktrees_file(
    worktree_pair: tuple[Path, Path],
) -> None:
    main, linked = worktree_pair
    config = _write(main, "profile = fast\n")  # gitignored in real use: absent from the worktree

    assert find_repo_config(linked) == config


def test_the_profile_resolves_the_same_from_main_and_from_a_worktree(
    worktree_pair: tuple[Path, Path], config_home: Path
) -> None:
    main, linked = worktree_pair
    _write(main, "profile = fast\n")

    expected = config_home / "noesis" / "profiles" / "billing" / "fast.env"

    assert resolve_env_file(None, main) == expected
    assert resolve_env_file(None, linked) == expected


def test_a_tracked_config_inside_a_worktree_still_uses_the_main_folder_name(
    worktree_pair: tuple[Path, Path], config_home: Path
) -> None:
    _, linked = worktree_pair
    config = read_repo_config(_write(linked, "profile = fast\n"))

    assert (config.repo_name, config.legacy_repo_name) == ("billing", "billing-feature")
    assert profile_env_file(config) == config_home / "noesis" / "profiles" / "billing" / "fast.env"


def test_a_profile_stored_under_the_old_worktree_folder_name_is_still_found(
    worktree_pair: tuple[Path, Path], config_home: Path
) -> None:
    _, linked = worktree_pair
    _write(linked, "profile = fast\n")
    legacy = config_home / "noesis" / "profiles" / "billing-feature" / "fast.env"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("", encoding="utf-8")

    assert resolve_env_file(None, linked) == legacy
