"""Per-invocation CLI state shared between the root callback and the commands."""

from dataclasses import dataclass
from pathlib import Path

import typer

from noesis.core import (
    ClaudeCodeSettings,
    Environment,
    load_claude_code_settings,
    load_environment,
    resolve_env_file,
)


@dataclass(slots=True, kw_only=True)
class CliState:
    """What the root callback parsed.

    Attributes:
        env_file: Explicit configuration file, or None to resolve it from the repository
            (`.noesis-config`) or fall back to the default location.
    """

    env_file: Path | None = None

    def environment(self) -> Environment:
        """Load the settings for this invocation (explicit file, then repository profile)."""
        return load_environment(resolve_env_file(self.env_file, Path.cwd()))

    def claude_code(self) -> ClaudeCodeSettings:
        """Claude Code's location settings (independent of the noesis configuration file)."""
        return load_claude_code_settings()


def cli_state(context: typer.Context) -> CliState:
    """The `CliState` stored by the root callback (a fresh one when invoked directly)."""
    state: object = context.find_root().obj
    return state if isinstance(state, CliState) else CliState()
