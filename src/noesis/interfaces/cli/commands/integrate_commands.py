"""`noesis integrate`: connect noesis to an agent (Claude Code hooks)."""

import asyncio
import shlex
import shutil
import sys
from pathlib import Path
from typing import Annotated

import typer

from noesis.bounded_context.capture.application.dtos import AgentHookChangeDto, AgentHooksDto
from noesis.bounded_context.capture.application.handlers.commands import (
    InstallAgentHooksCommand,
    UninstallAgentHooksCommand,
)
from noesis.bounded_context.capture.application.handlers.queries import GetAgentHooksStatusQuery
from noesis.bounded_context.capture.infrastructure.outbound.agent_hooks import HOOK_SUBCOMMAND
from noesis.interfaces.cli import output
from noesis.interfaces.cli.bootstrap import AgentHooksHandlers, build_agent_hooks
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import IntegrationResponse
from noesis.interfaces.cli.state import cli_state

DEV_VENV_MARKER: str = "/.venv/"

integrate_app: typer.Typer = typer.Typer(help="Connect noesis to an agent.", no_args_is_help=True)
claude_code_app: typer.Typer = typer.Typer(
    help="Register noesis hooks in Claude Code's settings (preview first, write with --yes).",
    no_args_is_help=True,
)
integrate_app.add_typer(claude_code_app, name="claude-code")

SettingsOption = Annotated[
    Path | None,
    typer.Option(
        "--settings",
        help="Claude Code settings file (default: $CLAUDE_CONFIG_DIR/settings.json or ~/.claude/settings.json).",
        dir_okay=False,
    ),
]
YesOption = Annotated[
    bool, typer.Option("--yes", help="Write the change (without it, only preview the diff).")
]


def _handlers(context: typer.Context, settings: Path | None) -> AgentHooksHandlers:
    return build_agent_hooks(cli_state(context).claude_code(), settings_file=settings)


def _result(change: AgentHookChangeDto, *, warning: str | None = None) -> IntegrationResponse:
    return IntegrationResponse.model_validate(change).model_copy(update={"warning": warning})


def _format(result: IntegrationResponse) -> str:
    lines: list[str] = []
    if result.diff:
        lines.append(result.diff.rstrip("\n"))
    if not result.changed:
        lines.append(f"{result.settings_file}: already up to date")
    elif result.applied:
        lines.append(
            f"wrote {result.settings_file}"
            + (f" (backup: {result.backup})" if result.backup else "")
        )
        lines.append("Restart Claude Code sessions so they load the hooks.")
    else:
        lines.append("Preview only. Re-run with --yes to write this change.")
    lines += [f"{event}: {', '.join(commands)}" for event, commands in result.installed.items()]
    if result.warning:
        lines.append(f"warning: {result.warning}")
    return "\n".join(lines)


def _format_status(result: IntegrationResponse) -> str:
    missing: str = (
        "installed" if not result.missing_events else "missing " + ", ".join(result.missing_events)
    )
    return "\n".join(
        [f"{result.settings_file}: {missing}"]
        + [f"{event}: {', '.join(commands)}" for event, commands in result.installed.items()]
    )


def hook_command(context: typer.Context) -> str:
    """The command Claude Code should run: the installed `noesis`, else this interpreter."""
    program: str | None = shutil.which("noesis")
    parts: list[str] = [program] if program else [sys.executable, "-m", "noesis"]
    env_file: Path | None = cli_state(context).env_file
    if env_file is not None:
        parts += ["--env-file", str(env_file.expanduser().resolve())]
    return " ".join(shlex.quote(part) for part in parts) + f" {HOOK_SUBCOMMAND}"


@claude_code_app.command("install")
def install(
    context: typer.Context,
    settings: SettingsOption = None,
    command: Annotated[
        str | None, typer.Option("--command", help="Hook command to register (default: detected).")
    ] = None,
    yes: YesOption = False,
    as_json: JsonOption = False,
) -> None:
    """Add noesis hooks (PostToolUse git commit, Stop, SessionEnd); other hooks are kept."""
    resolved: str = command or hook_command(context)
    change: AgentHookChangeDto = asyncio.run(
        _handlers(context, settings).install.handle(
            InstallAgentHooksCommand(hook_command=resolved, apply=yes)
        )
    )
    warning: str | None = (
        "the hook command points into a development .venv; run `make install` "
        "and use the installed `noesis`, or pass --command."
        if DEV_VENV_MARKER in resolved
        else None
    )
    output.emit(_result(change, warning=warning), _format)


@claude_code_app.command("uninstall")
def uninstall(
    context: typer.Context,
    settings: SettingsOption = None,
    yes: YesOption = False,
    as_json: JsonOption = False,
) -> None:
    """Remove every noesis hook; other hooks are kept."""
    change: AgentHookChangeDto = asyncio.run(
        _handlers(context, settings).uninstall.handle(UninstallAgentHooksCommand(apply=yes))
    )
    output.emit(_result(change), _format)


@claude_code_app.command("status")
def status(
    context: typer.Context, settings: SettingsOption = None, as_json: JsonOption = False
) -> None:
    """Show which noesis hooks are registered."""
    hooks: AgentHooksDto = asyncio.run(
        _handlers(context, settings).status.handle(GetAgentHooksStatusQuery())
    )
    output.emit(IntegrationResponse.model_validate(hooks), _format_status)
