"""Recognising `git commit` in shell command lines."""

import pytest

from noesis.utils import is_git_commit, split_commands

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m x",
        "cd repo && git add . && git commit -m x",
        'git add a && git commit -m "feat: x\n\nCo-Authored-By: y <z@example.com>"',
        "git -C /tmp/r -c user.name=n commit --amend",
        "sudo git commit -m x",
        "/usr/bin/git commit",
    ],
)
def test_commits_are_recognised(command: str) -> None:
    assert is_git_commit(command)


@pytest.mark.parametrize(
    "command",
    [
        None,
        "",
        "git status",
        'echo "git commit"',
        "echo 'a\ngit commit'",
        "python3 x.py commit",
        "git",
    ],
)
def test_other_commands_are_not_commits(command: str | None) -> None:
    assert not is_git_commit(command)


def test_split_keeps_quoted_separators_and_escapes() -> None:
    assert split_commands('a "x && y" && b | c; d\ne') == ['a "x && y" ', " b ", " c", " d", "e"]
    assert split_commands(r"echo a\;b") == [r"echo a\;b"]
