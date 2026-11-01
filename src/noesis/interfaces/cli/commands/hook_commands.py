"""`noesis hook <agent>`: entry points called by agent hooks. They never fail the session."""

import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path

import typer
from pydantic import ValidationError

from noesis.bounded_context.capture.application.handlers.commands import RecordCommitCommand
from noesis.bounded_context.capture.infrastructure.inbound.claude_code import (
    CaptureCommand,
    ClaudeCodeHookPayload,
    route,
)
from noesis.core import (
    Environment,
    default_state_dir,
)
from noesis.interfaces.cli.bootstrap import CAPTURE_FOLDER, CaptureHandlers, build_capture
from noesis.interfaces.cli.state import cli_state

RECURSION_GUARD: str = "NOESIS_HOOK"
ERROR_LOG: str = "hook-errors.log"

hook_app: typer.Typer = typer.Typer(
    help="Entry points for agent hooks (read the hook JSON on stdin, print nothing, always exit 0).",
    no_args_is_help=True,
)


async def _dispatch(handlers: CaptureHandlers, command: CaptureCommand) -> None:
    if isinstance(command, RecordCommitCommand):
        await handlers.record_commit.handle(command)
    else:
        await handlers.flush.handle(command)


def _log_failure(environment: Environment | None, error: BaseException) -> None:
    """Append the failure to `<state dir>/capture/hook-errors.log`; never raise from here."""
    try:
        folder: Path = (
            environment.runtime.state_dir if environment else default_state_dir()
        ) / CAPTURE_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / ERROR_LOG).open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {type(error).__name__}: {error}\n")
            handle.write("".join(traceback.format_exception(error)[-3:]))
    except OSError:
        pass


@hook_app.command("claude-code")
def claude_code(context: typer.Context) -> None:
    """Handle one Claude Code hook event (PostToolUse git commit, Stop, SessionEnd)."""
    if os.environ.get(RECURSION_GUARD) == "1":  # the curator's own Claude run: do nothing
        return
    environment: Environment | None = None
    try:
        payload: ClaudeCodeHookPayload = ClaudeCodeHookPayload.model_validate(json.load(sys.stdin))
        command: CaptureCommand | None = route(payload)
        if command is None:
            return
        environment = cli_state(context).environment()
        asyncio.run(_dispatch(build_capture(environment), command))
    except json.JSONDecodeError, ValidationError:
        return  # not a payload we understand: ignore silently
    except Exception as error:
        _log_failure(environment, error)
