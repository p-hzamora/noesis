"""Per-repository configuration: a `.noesis-config` pointer to a profile.

A repository commits `.noesis-config` at its root with one line, `profile = <name>`. The
profile itself lives outside the repository, in `~/.config/noesis/profiles/<repo>/<name>.env`,
so secrets and executable paths never travel with the code. Each repository gets its own
folder under `profiles/`, which leaves room for per-repository metadata later.

Lookup starts at the working directory and stops at the git root (the first directory that
holds `.git`), so a `.noesis-config` in a parent repository is never picked up by mistake.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from noesis.exceptions import InvalidConfigurationError

from .configurations import default_config_dir

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
    """

    path: Path
    profile: str

    @property
    def repo_name(self) -> str:
        """The repository folder name, used as the profile subfolder."""
        return self.path.parent.name


def find_repo_config(start: Path) -> Path | None:
    """The nearest `.noesis-config` from `start` up to (and including) the git root.

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
            return None
    return None


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
    return RepoConfig(path=path, profile=profile)


def profile_env_file(config: RepoConfig) -> Path:
    """`~/.config/noesis/profiles/<repo>/<profile>.env` for this repository config."""
    return default_config_dir() / PROFILES_DIR_NAME / config.repo_name / f"{config.profile}.env"


def resolve_env_file(explicit: Path | None, cwd: Path) -> Path | None:
    """The `.env` to read, by precedence: explicit (`--env-file`), then the repository
    profile, then None (the default location).

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
    return profile_env_file(read_repo_config(found))


__all__ = [
    "REPO_CONFIG_FILE_NAME",
    "RepoConfig",
    "find_repo_config",
    "profile_env_file",
    "read_repo_config",
    "resolve_env_file",
]
