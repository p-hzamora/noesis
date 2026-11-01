"""Wires and runs the host-level diagnostics."""

from pathlib import Path

from noesis.bounded_context.capture.application.dtos import AgentHooksDto
from noesis.bounded_context.capture.application.handlers.queries import GetAgentHooksStatusQuery
from noesis.core import ClaudeCodeSettings, Environment
from noesis.diagnostics.application.dtos import DiagnosticReportDto
from noesis.diagnostics.application.handlers.queries import (
    RunDiagnosticsHandler,
    RunDiagnosticsQuery,
)
from noesis.diagnostics.infrastructure.outbound.probes import SystemEnvironmentProbeAdapter
from noesis.exceptions import AgentSettingsInvalidError

from .agent_hooks_handlers_builder import build_agent_hooks


def build_diagnostics() -> RunDiagnosticsHandler:
    """Wire the diagnostics handler with the probe of the real system."""
    return RunDiagnosticsHandler(probe=SystemEnvironmentProbeAdapter())


async def run_diagnostics(
    environment: Environment, claude_code: ClaudeCodeSettings
) -> DiagnosticReportDto:
    """Gather what diagnostics inspects and run it.

    The installed hook events come from Capture's status query and are handed over as plain
    values, so Diagnostics never sees a Capture type. An unreadable agent settings file is
    reported as a failed check, not as an error.

    Args:
        environment: Loaded settings.
        claude_code: Where Claude Code keeps its settings.

    Returns:
        The diagnostics report.
    """
    settings_file: Path = claude_code.settings_file.expanduser()
    installed_events: tuple[str, ...] | None
    try:
        hooks: AgentHooksDto = await build_agent_hooks(claude_code).status.handle(
            GetAgentHooksStatusQuery()
        )
        installed_events = tuple(hooks.installed)
    except AgentSettingsInvalidError, OSError:
        installed_events = None
    query: RunDiagnosticsQuery = RunDiagnosticsQuery(
        env_file=environment.env_file,
        vault_dir=environment.knowledge.vault_dir,
        state_dir=environment.runtime.state_dir,
        curator_binary=environment.curator.claude_bin,
        hooks_settings_file=settings_file,
        installed_hook_events=installed_events,
    )
    return await build_diagnostics().handle(query)
