"""`noesis capture`: switch capture on or off for a session, and inspect it."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from noesis.bounded_context.capture.application.dtos import CaptureStatusDto
from noesis.bounded_context.capture.application.handlers.commands import (
    DisableCaptureCommand,
    EnableCaptureCommand,
)
from noesis.bounded_context.capture.application.handlers.queries import (
    GetCaptureStatusQuery,
    ListCaptureRunsQuery,
)
from noesis.bounded_context.capture.domain.value_objects import CaptureModeEnum
from noesis.core import Environment
from noesis.interfaces.cli import output
from noesis.interfaces.cli.bootstrap import CaptureHandlers, build_capture
from noesis.interfaces.cli.options import JsonOption, SessionOption
from noesis.interfaces.cli.responses import CaptureRunListResponse, CaptureStatusResponse
from noesis.interfaces.cli.state import cli_state

capture_app: typer.Typer = typer.Typer(
    help="Switch capture on or off for an agent session, and inspect what it did.",
    no_args_is_help=True,
)


def _handlers(context: typer.Context) -> CaptureHandlers:
    return build_capture(cli_state(context).environment())


def _status(context: typer.Context, dto: CaptureStatusDto) -> CaptureStatusResponse:
    """The status plus where it lives, so callers can match it against the hooks' config."""
    environment: Environment = cli_state(context).environment()
    vault: Path | None = environment.knowledge.vault_dir
    return CaptureStatusResponse.model_validate(dto).model_copy(
        update={
            "env_file": str(environment.env_file),
            "state_dir": str(environment.runtime.state_dir),
            "vault_dir": str(vault) if vault is not None else None,
        }
    )


def _format_status(status: CaptureStatusResponse) -> str:
    state: str = f"on ({status.mode})" if status.enabled else "off"
    pending: str = (
        f"{status.pending_commits} commit(s), {status.pending_files} file(s), {status.pending_lines} line(s)"
        if status.pending_commits
        else "none"
    )
    return (
        f"session {status.session_id}: {state}\n"
        f"pending: {pending}\n"
        f"last hand-over: {status.last_handover_at or 'never'}\n"
        f"env file: {status.env_file}\n"
        f"state dir: {status.state_dir}\n"
        f"vault: {status.vault_dir or 'not set'}"
    )


def _format_runs(runs: CaptureRunListResponse) -> str:
    if not runs.runs:
        return f"session {runs.session_id}: nothing journaled yet"
    lines: list[str] = []
    for run in runs.runs:
        lines.append(f"{run.at}  {run.outcome:<20} {run.detail}")
        if run.reference:
            lines.append(f"{'':21}brief: {run.reference}")
        if run.result is not None:
            lines.append(f"{'':21}result: {'ok' if run.result.get('ok') else 'failed'}")
    return "\n".join(lines)


@capture_app.command("on")
def capture_on(
    context: typer.Context,
    session: SessionOption,
    mode: Annotated[
        CaptureModeEnum,
        typer.Option("--mode", help="live: curate into the vault; dry-run: only store briefs."),
    ] = CaptureModeEnum.LIVE,
    as_json: JsonOption = False,
) -> None:
    """Switch capture on for a session."""
    command: EnableCaptureCommand = EnableCaptureCommand(session_id=session, mode=mode)
    status: CaptureStatusResponse = _status(
        context, asyncio.run(_handlers(context).enable.handle(command))
    )
    output.emit(status, _format_status)


@capture_app.command("off")
def capture_off(
    context: typer.Context, session: SessionOption, as_json: JsonOption = False
) -> None:
    """Switch capture off for a session (pending work is kept)."""
    status: CaptureStatusResponse = _status(
        context,
        asyncio.run(_handlers(context).disable.handle(DisableCaptureCommand(session_id=session))),
    )
    output.emit(status, _format_status)


@capture_app.command("status")
def capture_status(
    context: typer.Context, session: SessionOption, as_json: JsonOption = False
) -> None:
    """Show whether capture is on and what is pending."""
    status: CaptureStatusResponse = _status(
        context,
        asyncio.run(_handlers(context).status.handle(GetCaptureStatusQuery(session_id=session))),
    )
    output.emit(status, _format_status)


@capture_app.command("runs")
def capture_runs(
    context: typer.Context,
    session: SessionOption,
    limit: Annotated[
        int, typer.Option("--limit", min=1, max=1000, help="Most recent entries.")
    ] = 50,
    as_json: JsonOption = False,
) -> None:
    """Show the session journal: marks, hand-overs, skips, and curation results."""
    query: ListCaptureRunsQuery = ListCaptureRunsQuery(session_id=session, limit=limit)
    runs: CaptureRunListResponse = CaptureRunListResponse.model_validate(
        asyncio.run(_handlers(context).runs.handle(query))
    )
    output.emit(runs, _format_runs)
