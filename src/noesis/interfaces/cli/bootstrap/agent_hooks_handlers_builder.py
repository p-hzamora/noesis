"""Wires the Capture context's agent-hook handlers."""

from dataclasses import dataclass
from pathlib import Path

from noesis.bounded_context.capture.application.handlers.commands import (
    InstallAgentHooksHandler,
    UninstallAgentHooksHandler,
)
from noesis.bounded_context.capture.application.handlers.queries import (
    GetAgentHooksStatusHandler,
)
from noesis.bounded_context.capture.application.ports.agent_hooks import IAgentHookRegistry
from noesis.bounded_context.capture.infrastructure.outbound.agent_hooks import (
    ClaudeCodeSettingsAdapter,
)
from noesis.core import ClaudeCodeSettings


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentHooksHandlers:
    """The agent-hook actions of the Capture context, wired.

    Attributes:
        install: Register the noesis hooks.
        uninstall: Remove the noesis hooks.
        status: Show which hooks are registered.
    """

    install: InstallAgentHooksHandler
    uninstall: UninstallAgentHooksHandler
    status: GetAgentHooksStatusHandler


def build_agent_hooks(
    claude_code: ClaudeCodeSettings, *, settings_file: Path | None = None
) -> AgentHooksHandlers:
    """Wire the agent-hook handlers for Claude Code's settings file.

    Args:
        claude_code: Where Claude Code keeps its settings (names the default file).
        settings_file: Settings file to edit instead of the default (`--settings`).

    Returns:
        The wired handlers.
    """
    registry: IAgentHookRegistry = ClaudeCodeSettingsAdapter(
        (settings_file or claude_code.settings_file).expanduser()
    )
    return AgentHooksHandlers(
        install=InstallAgentHooksHandler(registry=registry),
        uninstall=UninstallAgentHooksHandler(registry=registry),
        status=GetAgentHooksStatusHandler(registry=registry),
    )
