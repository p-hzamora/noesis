"""Check that configuration, folders, executables and agent hooks are ready."""

from pathlib import Path

from noesis.diagnostics.application.dtos import (
    DiagnosticCheckDto,
    DiagnosticReportDto,
    UpdateCheckDto,
)
from noesis.diagnostics.application.enums import GraphStoreStatusEnum, UpdateVerdictEnum
from noesis.diagnostics.application.ports.graph_store import GraphStoreSnapshot, IGraphStoreProbe
from noesis.diagnostics.application.ports.probes import IEnvironmentProbe
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject

from .check_for_update_handler import CheckForUpdateQuery


class RunDiagnosticsQuery(FrozenObject):
    """What to inspect, as plain values the composition root gathered.

    Attributes:
        env_file: The `.env` file in use (it may not exist).
        state_dir: Folder for noesis state (it may not exist yet).
        curator_binary: Executable that runs the curator.
        hooks_settings_file: Agent settings file whose hooks were inspected.
        installed_hook_events: Events with a noesis hook, or None when the settings file
            could not be read.
        update_package_dir: Folder of the installed package, to check for an update; None
            skips the `update` check.
        graph_store_steps: Names of the schema steps the store should have applied, in order.
        graph_store_configured: Whether the store connection is configured (the password is
            set); when False the `graph_store` check is a warning, not a failure.
    """

    env_file: Path
    state_dir: Path
    curator_binary: str
    hooks_settings_file: Path
    installed_hook_events: tuple[str, ...] | None
    update_package_dir: Path | None = None
    graph_store_steps: tuple[str, ...] = ()
    graph_store_configured: bool = True


class RunDiagnosticsHandler(IHandler[RunDiagnosticsQuery, DiagnosticReportDto]):
    """Runs every check, in a fixed order, against the probe."""

    def __init__(
        self,
        *,
        probe: IEnvironmentProbe,
        updates: IHandler[CheckForUpdateQuery, UpdateCheckDto] | None = None,
        graph_store: IGraphStoreProbe | None = None,
    ) -> None:
        self._graph_store: IGraphStoreProbe | None = graph_store
        self._probe: IEnvironmentProbe = probe
        self._updates: IHandler[CheckForUpdateQuery, UpdateCheckDto] | None = updates

    async def handle(self, action: RunDiagnosticsQuery) -> DiagnosticReportDto:
        """The report; `ok` is False when any check failed."""
        checks: tuple[DiagnosticCheckDto, ...] = (
            self._check_config_file(action.env_file),
            self._check_state_dir(action.state_dir),
            self._check_executable("git", "git", "needed to read commits"),
            self._check_executable(
                "curator", action.curator_binary, "the Claude Code CLI runs the curator"
            ),
            self._check_agent_hooks(action.hooks_settings_file, action.installed_hook_events),
            *await self._check_graph_store(action),
            *await self._check_update(action),
        )
        return DiagnosticReportDto(ok=all(check.ok for check in checks), checks=checks)

    async def _check_graph_store(
        self, action: RunDiagnosticsQuery
    ) -> tuple[DiagnosticCheckDto, ...]:
        """Reachable and initialised passes; unreachable, rejected or missing steps fail.

        An unset password is a warning, not a failure: a person who has not set up the
        store has nothing to check, and `record`/`store` name the missing variable when they run.
        """
        if not action.graph_store_configured:
            return (
                DiagnosticCheckDto(
                    name="graph_store",
                    ok=True,
                    warning=True,
                    detail="not configured (NOESIS_NEO4J_PASSWORD is not set)",
                    next_step="Set NOESIS_NEO4J_PASSWORD in your user-side profile to use the "
                    "record store.",
                ),
            )
        if self._graph_store is None:
            return ()
        snapshot: GraphStoreSnapshot = await self._graph_store.inspect()
        if snapshot.status is GraphStoreStatusEnum.UNREACHABLE:
            return (
                DiagnosticCheckDto(
                    name="graph_store",
                    ok=False,
                    detail=f"unreachable at {snapshot.uri}",
                    next_step=f"Start Neo4j and check NOESIS_NEO4J_URI ({snapshot.uri}).",
                ),
            )
        if snapshot.status is GraphStoreStatusEnum.AUTHENTICATION_FAILED:
            return (
                DiagnosticCheckDto(
                    name="graph_store",
                    ok=False,
                    detail=f"reachable at {snapshot.uri}, credentials rejected",
                    next_step="Check NOESIS_NEO4J_USER and NOESIS_NEO4J_PASSWORD.",
                ),
            )
        if snapshot.status is GraphStoreStatusEnum.ERROR:
            return (
                DiagnosticCheckDto(
                    name="graph_store",
                    ok=False,
                    detail=f"reachable at {snapshot.uri}, but inspecting it failed: "
                    f"{snapshot.message}",
                    next_step="Run `noesis doctor` again; if it persists check the Neo4j logs.",
                ),
            )
        applied: list[str] = [
            name for name in action.graph_store_steps if name in snapshot.applied_steps
        ]
        missing: list[str] = [
            name for name in action.graph_store_steps if name not in snapshot.applied_steps
        ]
        detail: str = (
            f"reachable at {snapshot.uri}; schema steps applied: {', '.join(applied) or 'none'}"
        )
        if missing:
            return (
                DiagnosticCheckDto(
                    name="graph_store",
                    ok=False,
                    detail=f"{detail}; missing: {', '.join(missing)}",
                    next_step="Run `noesis store init`.",
                ),
            )
        return (DiagnosticCheckDto(name="graph_store", ok=True, detail=detail),)

    async def _check_update(self, action: RunDiagnosticsQuery) -> tuple[DiagnosticCheckDto, ...]:
        """Warn-only: anything but up to date is worth knowing about but never fails the run."""
        if self._updates is None or action.update_package_dir is None:
            return ()
        update: UpdateCheckDto = await self._updates.handle(
            CheckForUpdateQuery(package_dir=action.update_package_dir)
        )
        return (
            DiagnosticCheckDto(
                name="update",
                ok=True,
                detail=update.reason,
                next_step="; ".join(update.next_steps) or None,
                warning=update.verdict is not UpdateVerdictEnum.UP_TO_DATE,
            ),
        )

    def _check_config_file(self, env_file: Path) -> DiagnosticCheckDto:
        state: str = "found" if self._probe.is_file(env_file) else "not created, defaults in use"
        return DiagnosticCheckDto(name="config_file", ok=True, detail=f"{env_file} ({state})")

    def _check_state_dir(self, state: Path) -> DiagnosticCheckDto:
        existing: Path = next(
            (folder for folder in (state, *state.parents) if self._probe.exists(folder)),
            Path("/"),
        )
        if self._probe.is_writable_folder(
            existing
        ):  # noesis creates the missing folders on first use
            return DiagnosticCheckDto(name="state_dir", ok=True, detail=str(state))
        return DiagnosticCheckDto(
            name="state_dir",
            ok=False,
            detail=f"{state} is not writable",
            next_step="Set NOESIS_STATE_DIR to a writable folder.",
        )

    def _check_executable(self, name: str, command: str, purpose: str) -> DiagnosticCheckDto:
        found: str | None = self._probe.find_executable(command)
        if found:
            return DiagnosticCheckDto(name=name, ok=True, detail=found)
        return DiagnosticCheckDto(
            name=name,
            ok=False,
            detail=f"`{command}` not found on PATH",
            next_step=f"Install `{command}` ({purpose}) or fix PATH.",
        )

    @staticmethod
    def _check_agent_hooks(
        settings_file: Path, installed_events: tuple[str, ...] | None
    ) -> DiagnosticCheckDto:
        """Informational: capture from Claude Code needs the hooks; other uses do not."""
        if installed_events is None:
            return DiagnosticCheckDto(
                name="claude_code_hooks",
                ok=False,
                detail=f"{settings_file} is not valid JSON",
                next_step=f"Fix {settings_file}, then run `noesis integrate claude-code status`.",
            )
        if installed_events:
            return DiagnosticCheckDto(
                name="claude_code_hooks",
                ok=True,
                detail=f"installed: {', '.join(sorted(installed_events))}",
            )
        return DiagnosticCheckDto(
            name="claude_code_hooks",
            ok=True,
            detail="not installed (capture from Claude Code is off)",
            next_step="Run `noesis integrate claude-code install` to enable capture.",
        )
