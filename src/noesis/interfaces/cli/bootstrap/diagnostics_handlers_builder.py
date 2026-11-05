"""Wires and runs the host-level diagnostics."""

from pathlib import Path

import noesis
from noesis.bounded_context.capture.application.dtos import AgentHooksDto
from noesis.bounded_context.capture.application.handlers.queries import GetAgentHooksStatusQuery
from noesis.core import ClaudeCodeSettings, Environment
from noesis.diagnostics.application.dtos import DiagnosticReportDto, UpdateCheckDto
from noesis.diagnostics.application.handlers.queries import (
    CheckForUpdateHandler,
    CheckForUpdateQuery,
    RunDiagnosticsHandler,
    RunDiagnosticsQuery,
)
from noesis.diagnostics.infrastructure.outbound.probes import (
    ObsidianMcpProbeAdapter,
    SystemEnvironmentProbeAdapter,
)
from noesis.diagnostics.infrastructure.outbound.updates import GitCheckoutInspectorAdapter
from noesis.exceptions import AgentSettingsInvalidError
from noesis.shared_kernel.enums import SearchEngineEnum, WriterBackendEnum

from .agent_hooks_handlers_builder import build_agent_hooks
from .knowledge_handlers_builder import needs_vault
from .obsidian_mcp_client_builder import build_obsidian_mcp_client

UPDATE_CHECK_TIMEOUT_SECONDS: float = (
    15.0  # `noesis update check`: the user asked, so wait for the network
)
DOCTOR_UPDATE_TIMEOUT_SECONDS: float = 3.0  # `noesis doctor`: a side check must not slow the run


def installed_package_dir() -> Path:
    """Folder of the running `noesis` package (inside the checkout for an editable install)."""
    return Path(noesis.__file__).resolve().parent


def build_update_check(timeout_seconds: float) -> CheckForUpdateHandler:
    """Wire the update check with the `git` executable and the given time budget."""
    return CheckForUpdateHandler(
        inspector=GitCheckoutInspectorAdapter(timeout_seconds=timeout_seconds)
    )


async def run_update_check() -> UpdateCheckDto:
    """Check the running installation against its origin, with the `update check` budget."""
    return await build_update_check(UPDATE_CHECK_TIMEOUT_SECONDS).handle(
        CheckForUpdateQuery(package_dir=installed_package_dir())
    )


def build_diagnostics(environment: Environment | None = None) -> RunDiagnosticsHandler:
    """Wire the diagnostics handler with the probes of the real system.

    The Obsidian MCP probe is wired only when `NOESIS_SEARCH_BACKEND=obsidian-mcp` or
    `NOESIS_WRITER_BACKEND=mcp`, so the default configuration never makes an MCP call.
    """
    obsidian: ObsidianMcpProbeAdapter | None = None
    if environment is not None and (uses_obsidian_mcp(environment) or uses_mcp_writer(environment)):
        obsidian = ObsidianMcpProbeAdapter(build_obsidian_mcp_client(environment))
    return RunDiagnosticsHandler(
        probe=SystemEnvironmentProbeAdapter(),
        obsidian=obsidian,
        updates=build_update_check(DOCTOR_UPDATE_TIMEOUT_SECONDS),
    )


def uses_obsidian_mcp(environment: Environment) -> bool:
    """Whether notes are searched through Obsidian's MCP server."""
    return environment.knowledge.search_backend is SearchEngineEnum.OBSIDIAN_MCP


def uses_mcp_writer(environment: Environment) -> bool:
    """Whether notes are written through Obsidian's MCP server."""
    return environment.knowledge.writer_backend is WriterBackendEnum.MCP


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
    query = RunDiagnosticsQuery(
        env_file=environment.env_file,
        vault_dir=environment.knowledge.vault_dir,
        state_dir=environment.runtime.state_dir,
        curator_binary=environment.curator.claude_bin,
        hooks_settings_file=settings_file,
        installed_hook_events=installed_events,
        obsidian_mcp_url=environment.knowledge.obsidian_mcp_url
        if uses_obsidian_mcp(environment)
        else None,
        writer_mcp_url=environment.knowledge.obsidian_mcp_url
        if uses_mcp_writer(environment)
        else None,
        vault_required=needs_vault(environment),
        update_package_dir=installed_package_dir(),
    )
    return await build_diagnostics(environment).handle(query)
