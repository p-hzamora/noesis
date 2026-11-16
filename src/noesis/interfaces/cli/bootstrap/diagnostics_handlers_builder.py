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
from noesis.diagnostics.application.ports.graph_store import IGraphStoreProbe
from noesis.diagnostics.infrastructure.outbound.graph_store import Neo4jGraphStoreProbeAdapter
from noesis.diagnostics.infrastructure.outbound.probes import SystemEnvironmentProbeAdapter
from noesis.diagnostics.infrastructure.outbound.updates import GitCheckoutInspectorAdapter
from noesis.exceptions import AgentSettingsInvalidError

from .agent_hooks_handlers_builder import build_agent_hooks
from .knowledge_handlers_builder import registered_schema_step_names

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


def build_diagnostics(environment: Environment) -> RunDiagnosticsHandler:
    """Wire the diagnostics handler with the probes of the real system.

    The graph store probe is built only when the password is set; building it opens no
    connection (the handler's query decides whether it runs).
    """
    graph_store: IGraphStoreProbe | None = (
        Neo4jGraphStoreProbeAdapter(environment.knowledge.neo4j_connection())
        if environment.knowledge.neo4j_password is not None
        else None
    )
    return RunDiagnosticsHandler(
        probe=SystemEnvironmentProbeAdapter(),
        updates=build_update_check(DOCTOR_UPDATE_TIMEOUT_SECONDS),
        graph_store=graph_store,
    )


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
        state_dir=environment.runtime.state_dir,
        curator_binary=environment.curator.claude_bin,
        hooks_settings_file=settings_file,
        installed_hook_events=installed_events,
        update_package_dir=installed_package_dir(),
        graph_store_steps=registered_schema_step_names(),
        graph_store_configured=environment.knowledge.neo4j_password is not None,
    )
    return await build_diagnostics(environment).handle(query)
