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
from noesis.diagnostics.infrastructure.outbound.probes import (
    ObsidianMcpProbeAdapter,
    SystemEnvironmentProbeAdapter,
)
from noesis.exceptions import AgentSettingsInvalidError
from noesis.shared_kernel.enums import SearchEngineEnum
from noesis.shared_kernel.infrastructure.outbound.mcp import ObsidianMcpClient

from .agent_hooks_handlers_builder import build_agent_hooks


def build_diagnostics(environment: Environment | None = None) -> RunDiagnosticsHandler:
    """Wire the diagnostics handler with the probes of the real system.

    The Obsidian MCP probe is wired only when `NOESIS_SEARCH_BACKEND=obsidian-mcp`, so the
    default configuration never makes an MCP call.
    """
    obsidian: ObsidianMcpProbeAdapter | None = None
    if environment is not None and uses_obsidian_mcp(environment):
        settings = environment.knowledge
        token = settings.obsidian_mcp_token
        obsidian = ObsidianMcpProbeAdapter(
            ObsidianMcpClient(
                settings.obsidian_mcp_url,
                token=token.get_secret_value() if token else None,
                timeout_seconds=settings.obsidian_mcp_timeout_seconds,
            )
        )
    return RunDiagnosticsHandler(probe=SystemEnvironmentProbeAdapter(), obsidian=obsidian)


def uses_obsidian_mcp(environment: Environment) -> bool:
    """Whether notes are searched through Obsidian's MCP server."""
    return environment.knowledge.search_backend is SearchEngineEnum.OBSIDIAN_MCP


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
        obsidian_mcp_url=environment.knowledge.obsidian_mcp_url
        if uses_obsidian_mcp(environment)
        else None,
    )
    return await build_diagnostics(environment).handle(query)
