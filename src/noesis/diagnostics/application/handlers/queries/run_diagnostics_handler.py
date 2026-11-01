"""Check that configuration, folders, executables and agent hooks are ready."""

from pathlib import Path

from noesis.diagnostics.application.dtos import DiagnosticCheckDto, DiagnosticReportDto
from noesis.diagnostics.application.ports.probes import IEnvironmentProbe
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class RunDiagnosticsQuery(FrozenObject):
    """What to inspect, as plain values the composition root gathered.

    Attributes:
        env_file: The `.env` file in use (it may not exist).
        vault_dir: Configured vault folder, or None when unset.
        state_dir: Folder for noesis state (it may not exist yet).
        curator_binary: Executable that runs the curator.
        hooks_settings_file: Agent settings file whose hooks were inspected.
        installed_hook_events: Events with a noesis hook, or None when the settings file
            could not be read.
    """

    env_file: Path
    vault_dir: Path | None
    state_dir: Path
    curator_binary: str
    hooks_settings_file: Path
    installed_hook_events: tuple[str, ...] | None


class RunDiagnosticsHandler(IHandler[RunDiagnosticsQuery, DiagnosticReportDto]):
    """Runs every check, in a fixed order, against the probe."""

    def __init__(self, *, probe: IEnvironmentProbe) -> None:
        self._probe: IEnvironmentProbe = probe

    async def handle(self, action: RunDiagnosticsQuery) -> DiagnosticReportDto:
        """The report; `ok` is False when any check failed."""
        checks: tuple[DiagnosticCheckDto, ...] = (
            self._check_config_file(action.env_file),
            self._check_vault(action.vault_dir),
            self._check_state_dir(action.state_dir),
            self._check_executable("git", "git", "needed to read commits"),
            self._check_executable(
                "curator", action.curator_binary, "the Claude Code CLI runs the curator"
            ),
            self._check_agent_hooks(action.hooks_settings_file, action.installed_hook_events),
        )
        return DiagnosticReportDto(ok=all(check.ok for check in checks), checks=checks)

    def _check_config_file(self, env_file: Path) -> DiagnosticCheckDto:
        state: str = "found" if self._probe.is_file(env_file) else "not created, defaults in use"
        return DiagnosticCheckDto(name="config_file", ok=True, detail=f"{env_file} ({state})")

    def _check_vault(self, vault: Path | None) -> DiagnosticCheckDto:
        if vault is None:
            return DiagnosticCheckDto(
                name="vault",
                ok=False,
                detail="NOESIS_VAULT_DIR is not set",
                next_step="Run `noesis config init --vault-dir <folder>`.",
            )
        if not self._probe.is_writable_folder(vault):
            return DiagnosticCheckDto(
                name="vault",
                ok=False,
                detail=f"{vault} is missing or not writable",
                next_step=f"Create {vault} or point NOESIS_VAULT_DIR at a writable folder.",
            )
        return DiagnosticCheckDto(name="vault", ok=True, detail=str(vault))

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
