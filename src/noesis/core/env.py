"""The single entry point to noesis configuration.

Every settings class in `noesis.core.configurations` is built here and nowhere else: the
interfaces read `.env` values and default locations only through this module. Unlike a web
service, the `.env` path is chosen per invocation (`--env-file`), so settings are loaded by
`load_environment` instead of at import time.
"""

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from noesis.core.configurations import (
    AppBaseSettings,
    CaptureSettings,
    ClaudeCodeSettings,
    CuratorSettings,
    KnowledgeSettings,
    RuntimeSettings,
    default_env_file,
    default_state_dir,
)
from noesis.exceptions import (
    InvalidConfigurationError,
)
from noesis.shared_kernel.domain import (
    JsonValue,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Environment:
    """All noesis settings of one process.

    Attributes:
        env_file: The `.env` file that was read (it may not exist).
        runtime: State folder and logging.
        knowledge: Where notes are stored.
        capture: Capture thresholds.
        curator: Curator run settings.
    """

    env_file: Path
    runtime: RuntimeSettings
    knowledge: KnowledgeSettings
    capture: CaptureSettings
    curator: CuratorSettings


def load_environment(env_file: Path | None = None) -> Environment:
    """Read settings from `env_file` (default `~/.config/noesis/.env`) and the environment.

    Environment variables override values from the file.

    Args:
        env_file: `.env` file to read; a missing file is fine.

    Returns:
        The validated settings.

    Raises:
        InvalidConfigurationError: A value failed validation.
    """
    path: Path = (env_file or default_env_file()).expanduser()
    problems: list[JsonValue] = []
    runtime: RuntimeSettings | None = _load(RuntimeSettings, path, problems)
    knowledge: KnowledgeSettings | None = _load(KnowledgeSettings, path, problems)
    capture: CaptureSettings | None = _load(CaptureSettings, path, problems)
    curator: CuratorSettings | None = _load(CuratorSettings, path, problems)
    if runtime is None or knowledge is None or capture is None or curator is None:
        raise InvalidConfigurationError(
            f"Invalid configuration in {path} or the environment.",
            {"env_file": str(path), "problems": problems},
            next_steps=[f"Fix the variables listed in 'problems' (in {path} or the environment)."],
        )
    return Environment(
        env_file=path, runtime=runtime, knowledge=knowledge, capture=capture, curator=curator
    )


def load_claude_code_settings() -> ClaudeCodeSettings:
    """Claude Code's own location settings, from the process environment only.

    Kept apart from `load_environment`: `CLAUDE_CONFIG_DIR` belongs to Claude Code, so a
    noesis `.env` is not consulted and an invalid noesis configuration does not block it.
    """
    return ClaudeCodeSettings()


def _load[S: AppBaseSettings](
    settings_class: type[S], env_file: Path, problems: list[JsonValue]
) -> S | None:
    """Build one settings class, appending `VARIABLE: reason` lines to `problems` on failure."""
    try:
        return settings_class(_env_file=env_file)
    except ValidationError as error:
        prefix: str = str(settings_class.model_config.get("env_prefix", ""))
        problems.extend(
            f"{prefix}{'_'.join(str(part) for part in issue['loc']).upper()}: {issue['msg']}"
            for issue in error.errors()
        )
        return None


__all__ = [
    "ClaudeCodeSettings",
    "Environment",
    "default_env_file",
    "default_state_dir",
    "load_claude_code_settings",
    "load_environment",
]
