"""Locating the git repository a command runs in."""

import re
from pathlib import Path


def find_git_root(start: Path) -> Path | None:
    """The nearest directory from `start` upwards that holds `.git`.

    `.git` may be a folder or a file (a linked worktree), so both count.

    Args:
        start: Directory to begin the search in.

    Returns:
        The repository root, or None outside a repository.
    """
    current: Path = start.expanduser().resolve()
    for directory in (current, *current.parents):
        if (directory / ".git").exists():
            return directory
    return None


GIT_DIR_NAME: str = ".git"
_GITDIR_PREFIX: str = "gitdir:"


def find_common_dir(start: Path) -> Path | None:
    """The common git directory of the repository `start` belongs to.

    Every linked worktree of a repository shares one common directory, so it is the
    identity of the repository: `<main>/.git` for a normal checkout and its linked
    worktrees, the repository folder itself when bare, `<parent>/.git/modules/<name>` for a
    submodule. Read from the files git keeps (`.git`, `commondir`), without running git.

    Args:
        start: Directory to begin the search in.

    Returns:
        The resolved common directory, or None outside a repository.
    """
    root: Path | None = find_git_root(start)
    if root is None:
        return _find_bare_repository(start)
    marker: Path = root / GIT_DIR_NAME
    if marker.is_dir():
        return marker.resolve()
    try:
        text: str = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith(_GITDIR_PREFIX):
        return None
    git_dir: Path = (root / text.removeprefix(_GITDIR_PREFIX).strip()).resolve()
    pointer: Path = git_dir / "commondir"
    if pointer.is_file():  # a linked worktree: its git dir points at the shared one
        return (git_dir / pointer.read_text(encoding="utf-8").strip()).resolve()
    return git_dir


def repository_name(common_dir: Path) -> str:
    """The folder name a repository is known by: the single naming rule of noesis.

    `<main>/.git` is named after `<main>`, a submodule's `.git/modules/<name>` after `<name>`,
    and a bare repository after its own folder.
    """
    if common_dir.name == GIT_DIR_NAME:
        return common_dir.parent.name
    return common_dir.name


def find_main_repository(start: Path) -> Path | None:
    """The main worktree (or, for a bare repository, the repository folder) of `start`'s repository.

    Args:
        start: Directory to begin the search in.

    Returns:
        The path that identifies the repository, or None outside one.
    """
    common_dir: Path | None = find_common_dir(start)
    if common_dir is None:
        return None
    if common_dir.name == GIT_DIR_NAME:
        return common_dir.parent
    if GIT_DIR_NAME in common_dir.parts:  # a submodule: its own work tree
        return find_git_root(start)
    return common_dir


def _find_bare_repository(start: Path) -> Path | None:
    """The nearest folder from `start` upwards shaped like a bare repository."""
    current: Path = start.expanduser().resolve()
    for directory in (current, *current.parents):
        if (directory / "HEAD").is_file() and (directory / "objects").is_dir():
            return directory
    return None


_REMOTE_URL: re.Pattern[str] = re.compile(r"^\s*url\s*=\s*(\S+)\s*$")
_REMOTE_SECTION: re.Pattern[str] = re.compile(r'^\s*\[remote "([^"]+)"\]\s*$')
_SCHEME: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
PREFERRED_REMOTE: str = "origin"


def canonical_remote(url: str) -> str:
    """`host/path` of a remote URL: no scheme, no credentials, no port, no `.git`.

    `git@gitlab.com:org/repo.git` and `https://user@gitlab.com/org/repo` are both
    `gitlab.com/org/repo`.
    """
    text: str = url.strip()
    if _SCHEME.match(text):
        text = _SCHEME.sub("", text, count=1)
        authority, _, path = text.partition("/")
        text = f"{authority.rpartition('@')[2].partition(':')[0]}/{path}"
    else:  # scp-like: [user@]host:path
        host, _, path = text.partition(":")
        text = f"{host.rpartition('@')[2]}/{path}"
    return text.strip("/").removesuffix(".git")


def repository_remote(common_dir: Path) -> str | None:
    """The canonical URL of the repository's `origin` (else its first remote), or None.

    Read from the `config` file git keeps in the common directory, without running git.
    """
    try:
        lines: list[str] = (common_dir / "config").read_text(encoding="utf-8").splitlines()
    except OSError, UnicodeDecodeError:
        return None
    urls: dict[str, str] = {}
    current: str | None = None
    for line in lines:
        if section := _REMOTE_SECTION.match(line):
            current = section.group(1)
        elif line.lstrip().startswith("["):
            current = None
        elif current is not None and (url := _REMOTE_URL.match(line)):
            urls.setdefault(current, url.group(1))
    chosen: str | None = urls.get(PREFERRED_REMOTE) or next(iter(urls.values()), None)
    return canonical_remote(chosen) if chosen else None
