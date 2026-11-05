"""Real git repositories for tests: a local bare repository stands in for origin."""

import os
import subprocess
from pathlib import Path

import pytest


def isolate_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Commit without the user's git configuration and never prompt."""
    for name, value in {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }.items():
        monkeypatch.setenv(name, value)


def git(cwd: Path, *args: str) -> str:
    """stdout of `git -C cwd args`; raises when git fails."""
    result = subprocess.run(
        ["git", "-C", str(cwd), "-c", "commit.gpgsign=false", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def commit(repo: Path, name: str) -> str:
    """Create file `name` in `repo`, commit it and return the new HEAD sha."""
    (repo / name).write_text(name, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


class GitWorld:
    """An origin, a second clone that publishes, and the checkout under test."""

    def __init__(self, root: Path) -> None:
        self.origin: Path = root / "origin.git"
        self.publisher: Path = root / "publisher"
        self.checkout: Path = root / "checkout"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.publisher)], check=True)
        git(self.publisher, "checkout", "-q", "-b", "main")
        (self.publisher / "src/noesis").mkdir(parents=True)
        self.base: str = commit(self.publisher, "src/noesis/__init__.py")
        git(self.publisher, "push", "-q", "origin", "main")
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.checkout)], check=True)

    @property
    def package_dir(self) -> Path:
        """Where the package lives inside the checkout."""
        return self.checkout / "src/noesis"

    def publish(self, name: str) -> str:
        """Push a new commit to origin from the publisher clone; returns its sha."""
        sha: str = commit(self.publisher, name)
        git(self.publisher, "push", "-q", "origin", "main")
        return sha
