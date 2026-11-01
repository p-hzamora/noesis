"""Check that configuration, folders, executables and agent hooks are ready."""

from pathlib import Path

from noesis.diagnostics.application.dtos import DiagnosticCheckDto, DiagnosticReportDto
from noesis.diagnostics.application.ports.probes import IEnvironmentProbe, IObsidianMcpProbe
from noesis.exceptions import ObsidianMcpError
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
        obsidian_mcp_url: Obsidian MCP endpoint to probe, or None when notes are searched
            on the filesystem (then no MCP call is made).
    """

    env_file: Path
    vault_dir: Path | None
    state_dir: Path
    curator_binary: str
    hooks_settings_file: Path
    installed_hook_events: tuple[str, ...] | None
    obsidian_mcp_url: str | None = None


class RunDiagnosticsHandler(IHandler[RunDiagnosticsQuery, DiagnosticReportDto]):
    """Runs every check, in a fixed order, against the probe."""

    def __init__(
        self, *, probe: IEnvironmentProbe, obsidian: IObsidianMcpProbe | None = None
    ) -> None:
        self._probe: IEnvironmentProbe = probe
        self._obsidian: IObsidianMcpProbe | None = obsidian

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
            await self._check_search_backend(action),
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

    async def _check_search_backend(self, action: RunDiagnosticsQuery) -> DiagnosticCheckDto:
        """Whether Obsidian's MCP answers and serves the folder `NOESIS_VAULT_DIR` points at.

        Obsidian does not tell which folder it serves, so the root listings are compared:
        the same non-hidden names on both sides means the same vault.
        """
        if action.obsidian_mcp_url is None or self._obsidian is None:
            return DiagnosticCheckDto(
                name="search_backend",
                ok=True,
                detail="filesystem (Obsidian MCP not used)",
                next_step="Set NOESIS_SEARCH_BACKEND=obsidian-mcp to search through Obsidian.",
            )
        url: str = action.obsidian_mcp_url
        try:
            served: set[str] = {
                name for name in await self._obsidian.list_root() if not name.startswith(".")
            }
        except ObsidianMcpError as error:
            return DiagnosticCheckDto(
                name="search_backend",
                ok=False,
                detail=f"obsidian-mcp unreachable at {url}: {error.message}",
                next_step=(
                    "Start Obsidian with its MCP server (searches use files meanwhile), "
                    "or check NOESIS_OBSIDIAN_MCP_URL and NOESIS_OBSIDIAN_MCP_TOKEN."
                ),
            )
        if action.vault_dir is None:
            return DiagnosticCheckDto(
                name="search_backend",
                ok=True,
                detail=f"obsidian-mcp reachable at {url} (vault not compared: NOESIS_VAULT_DIR is not set)",
            )
        local: set[str] = {
            name for name in self._probe.list_entries(action.vault_dir) if not name.startswith(".")
        }
        if served != local:
            differing: list[str] = sorted(served ^ local)[:5]
            return DiagnosticCheckDto(
                name="search_backend",
                ok=False,
                detail=(
                    f"obsidian-mcp at {url} serves a different vault than {action.vault_dir} "
                    f"(entries only on one side: {', '.join(differing)})"
                ),
                next_step="Open the vault of NOESIS_VAULT_DIR in Obsidian, or point NOESIS_VAULT_DIR at the vault Obsidian serves.",
            )
        return DiagnosticCheckDto(
            name="search_backend",
            ok=True,
            detail=f"obsidian-mcp reachable at {url}, serving {action.vault_dir}",
        )
