"""Per-repository configuration: a `.noesis-config` pointer to a profile.

A repository commits `.noesis-config` at its root with one line, `profile = <name>`. The
profile itself lives outside the repository, in `~/.config/noesis/profiles/<repo>/<name>.env`,
so secrets and executable paths never travel with the code. Each repository gets its own
folder under `profiles/`, which leaves room for per-repository metadata later.

Lookup starts at the working directory and stops at the git root (the first directory that
holds `.git`), so a `.noesis-config` in a parent repository is never picked up by mistake.
A linked worktree has no `.noesis-config` of its own when the file is gitignored, so the lookup
then reads the main worktree's file. The profile folder is named after the main repository
folder, so a worktree and its main checkout share one profile.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from noesis.exceptions import InvalidConfigurationError

from .configurations import default_config_dir
from .git_root import find_common_dir, find_main_repository, repository_name

REPO_CONFIG_FILE_NAME: str = ".noesis-config"
PROFILE_KEY: str = "profile"
PROFILES_DIR_NAME: str = "profiles"
_PROFILE_NAME_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True, kw_only=True)
class RepoConfig:
    """A parsed `.noesis-config`.

    Attributes:
        path: The `.noesis-config` file that was read.
        profile: The profile name it selects.
        repo_name: The main repository folder name, used as the profile subfolder.
        legacy_repo_name: The folder the file sits in, which older versions used as the
            profile subfolder (differs from `repo_name` inside a linked worktree).
    """

    path: Path
    profile: str
    repo_name: str
    legacy_repo_name: str


def find_repo_config(start: Path) -> Path | None:
    """The nearest `.noesis-config` from `start` up to (and including) the git root.

    Inside a linked worktree with no config of its own, the main worktree's file applies.

    Args:
        start: Directory to begin the search in.

    Returns:
        The file path, or None when no repository config applies.
    """
    current: Path = start.expanduser().resolve()
    for directory in (current, *current.parents):
        candidate: Path = directory / REPO_CONFIG_FILE_NAME
        if candidate.is_file():
            return candidate
        if (directory / ".git").exists():
            return _main_worktree_config(directory)
    return None


def _main_worktree_config(worktree: Path) -> Path | None:
    """The main worktree's `.noesis-config` when `worktree` is a different, linked worktree."""
    main: Path | None = find_main_repository(worktree)
    if main is None or main == worktree:
        return None
    candidate: Path = main / REPO_CONFIG_FILE_NAME
    return candidate if candidate.is_file() else None


def read_repo_config(path: Path) -> RepoConfig:
    """Parse a `.noesis-config` file.

    The format is `key = value` lines; blank lines and lines starting with `#` are ignored.
    Only `profile` is accepted, so a repository cannot inject other settings.

    Args:
        path: The `.noesis-config` file.

    Returns:
        The parsed config.

    Raises:
        InvalidConfigurationError: The file is unreadable, has an unknown key, or names an
            invalid or missing profile.
    """
    values: dict[str, str] = {}
    try:
        lines: list[str] = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise InvalidConfigurationError(
            f"Cannot read {path}.",
            {"path": str(path), "reason": str(error)},
            next_steps=[f"Fix or remove {path}."],
        ) from error
    for number, raw in enumerate(lines, start=1):
        line: str = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key.strip() != PROFILE_KEY:
            raise InvalidConfigurationError(
                f"Unsupported line {number} in {path}: only '{PROFILE_KEY} = <name>' is allowed.",
                {"path": str(path), "line": number},
                next_steps=["Keep only 'profile = <name>' in the repository config."],
            )
        values[PROFILE_KEY] = value.strip()
    profile: str | None = values.get(PROFILE_KEY)
    if not profile or not _PROFILE_NAME_PATTERN.fullmatch(profile):
        raise InvalidConfigurationError(
            f"{path} must name a profile made of letters, digits, '-' or '_'.",
            {"path": str(path), "profile": profile or ""},
            next_steps=["Set 'profile = <name>' in the repository config."],
        )
    common_dir: Path | None = find_common_dir(path.parent)
    return RepoConfig(
        path=path,
        profile=profile,
        repo_name=repository_name(common_dir) if common_dir else path.parent.name,
        legacy_repo_name=path.parent.name,
    )


def profile_env_file(config: RepoConfig) -> Path:
    """`~/.config/noesis/profiles/<repo>/<profile>.env` for this repository config."""
    return _profile_file(config.repo_name, config.profile)


def _profile_file(repo_name: str, profile: str) -> Path:
    return default_config_dir() / PROFILES_DIR_NAME / repo_name / f"{profile}.env"


def resolve_env_file(explicit: Path | None, cwd: Path) -> Path | None:
    """The `.env` to read, by precedence: explicit (`--env-file`), then the repository
    profile (falling back to the profile an older version stored under the worktree folder name),
    then None (the default location).

    Args:
        explicit: The `--env-file` value, if any.
        cwd: The working directory to search from.

    Returns:
        The env file to read, or None to use the default.

    Raises:
        InvalidConfigurationError: A `.noesis-config` exists but cannot be read or is invalid.
    """
    if explicit is not None:
        return explicit
    found: Path | None = find_repo_config(cwd)
    if found is None:
        return None
    config: RepoConfig = read_repo_config(found)
    current: Path = profile_env_file(config)
    legacy: Path = _profile_file(config.legacy_repo_name, config.profile)
    if not current.exists() and legacy.exists():  # profiles made before the main-name rule
        return legacy
    return current


__all__ = [
    "REPO_CONFIG_FILE_NAME",
    "RepoConfig",
    "find_repo_config",
    "profile_env_file",
    "read_repo_config",
    "resolve_env_file",
]
