"""`noesis capture`: switch capture on or off for a session, and inspect it."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from noesis.bounded_context.capture.application.dtos import (
    CaptureRunListDto,
    CaptureStatusDto,
    ResolvedIdentityDto,
)
from noesis.bounded_context.capture.application.handlers.commands import (
    DisableCaptureCommand,
    EnableCaptureCommand,
)
from noesis.bounded_context.capture.application.handlers.queries import (
    GetCaptureStatusQuery,
    ListCaptureRunsQuery,
    ResolveSessionIdentityQuery,
)
from noesis.bounded_context.capture.domain.value_objects import CaptureModeEnum
from noesis.core import Environment
from noesis.exceptions import BlankSessionIdError, NotInGitRepositoryError, SelfParentSessionError
from noesis.interfaces.cli import output
from noesis.interfaces.cli.bootstrap import CaptureHandlers, build_capture
from noesis.interfaces.cli.options import JsonOption, SessionOption
from noesis.interfaces.cli.responses import CaptureRunListResponse, CaptureStatusResponse
from noesis.interfaces.cli.state import cli_state

capture_app: typer.Typer = typer.Typer(
    help="Switch capture on or off for an agent session, and inspect what it did.",
    no_args_is_help=True,
)


def _given(option: str, value: str | None) -> str | None:
    """`value` as typed, or None when the option was left out.

    Raises:
        BlankSessionIdError: The option was given but is empty or only whitespace.
    """
    if value is not None and not value.strip():
        raise BlankSessionIdError(
            f"{option} was given but is blank.",
            {"option": option},
            next_steps=[f"Pass a non-empty {option} value, or leave the option out."],
        )
    return value


async def _identity(
    handlers: CaptureHandlers,
    session: str | None,
    *,
    allow_fresh: bool = False,
    use_ambient: bool = True,
) -> ResolvedIdentityDto:
    """The stored session id (and repository) this command runs under.

    Raises:
        NotInGitRepositoryError: The working directory is outside any git repository, where no
            hook could ever match the session.
    """
    query = ResolveSessionIdentityQuery(
        hint=session, cwd=Path.cwd(), allow_fresh=allow_fresh, use_ambient=use_ambient
    )
    identity: ResolvedIdentityDto = await handlers.resolve.handle(query)
    if not identity.repo_id:
        raise NotInGitRepositoryError(
            f"{Path.cwd()} is not inside a git repository.",
            {"cwd": str(Path.cwd())},
            next_steps=["Run the command from inside the repository whose work is captured."],
        )
    return identity


def _status(
    environment: Environment, dto: CaptureStatusDto, *, generated: bool = False
) -> CaptureStatusResponse:
    """The status plus where it lives, so callers can match it against the hooks' config."""
    vault: Path | None = environment.notes.vault_dir
    return CaptureStatusResponse.model_validate(dto).model_copy(
        update={
            "env_file": str(environment.env_file),
            "state_dir": str(environment.runtime.state_dir),
            "vault_dir": str(vault) if vault is not None else None,
            "generated": generated,
        }
    )


async def _switch_on(
    handlers: CaptureHandlers, session: str | None, parent: str | None, mode: CaptureModeEnum | None
) -> tuple[CaptureStatusDto, ResolvedIdentityDto]:
    """Resolve the session (and its parent), then switch it on, in one event loop."""
    identity: ResolvedIdentityDto = await _identity(
        handlers, session, allow_fresh=True, use_ambient=parent is None
    )
    parent_id: str | None = None
    if parent is not None:  # never the harness' id: that one is the parent's own
        parent_id = (await _identity(handlers, parent, use_ambient=False)).session_id
        if parent_id == identity.session_id:
            raise SelfParentSessionError(
                "A session cannot be its own parent.",
                {"session_id": identity.session_id},
                next_steps=["Give the sub-agent its own --session, or omit it."],
            )
    command = EnableCaptureCommand(
        session_id=identity.session_id,
        mode=mode,
        repo_id=identity.repo_id,
        repository_path=identity.repository_path,
        parent_id=parent_id,
    )
    return await handlers.enable.handle(command), identity


@capture_app.command("on")
def capture_on(
    context: typer.Context,
    session: SessionOption = None,
    parent: Annotated[
        str | None,
        typer.Option(
            "--parent",
            help="Session that started this one as a sub-agent: it gets its own state, "
            "inherits the parent's mode, and shows up in `capture runs --children`.",
        ),
    ] = None,
    mode: Annotated[
        CaptureModeEnum | None,
        typer.Option(
            "--mode",
            help="live: curate into the vault; dry-run: only store briefs. Default: keep the "
            "session's mode (live for a new one).",
        ),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Switch capture on for a session (a repeat call keeps pending work and changes nothing)."""
    given_session: str | None = _given("--session", session)
    given_parent: str | None = _given("--parent", parent)
    environment: Environment = cli_state(context).environment()
    dto, identity = asyncio.run(
        _switch_on(build_capture(environment), given_session, given_parent, mode)
    )
    if identity.generated:
        output.warn(
            f"no session id was given or found, so noesis generated {identity.session_id}. "
            "No hook can match a generated id: switch capture on again with --session "
            "<the agent's own session id>, or pass this id as --session to later commands."
        )
    output.emit(_status(environment, dto, generated=identity.generated))


@capture_app.command("off")
def capture_off(
    context: typer.Context, session: SessionOption = None, as_json: JsonOption = False
) -> None:
    """Switch capture off for a session (pending work is kept)."""
    given: str | None = _given("--session", session)
    environment: Environment = cli_state(context).environment()
    handlers: CaptureHandlers = build_capture(environment)

    async def disable() -> CaptureStatusDto:
        identity: ResolvedIdentityDto = await _identity(handlers, given)
        return await handlers.disable.handle(DisableCaptureCommand(session_id=identity.session_id))

    output.emit(_status(environment, asyncio.run(disable())))


@capture_app.command("status")
def capture_status(
    context: typer.Context, session: SessionOption = None, as_json: JsonOption = False
) -> None:
    """Show whether capture is on and what is pending."""
    given: str | None = _given("--session", session)
    environment: Environment = cli_state(context).environment()
    handlers: CaptureHandlers = build_capture(environment)

    async def read() -> CaptureStatusDto:
        identity: ResolvedIdentityDto = await _identity(handlers, given)
        return await handlers.status.handle(GetCaptureStatusQuery(session_id=identity.session_id))

    output.emit(_status(environment, asyncio.run(read())))


@capture_app.command("runs")
def capture_runs(
    context: typer.Context,
    session: SessionOption = None,
    limit: Annotated[
        int, typer.Option("--limit", min=1, max=1000, help="Most recent entries.")
    ] = 50,
    children: Annotated[
        bool,
        typer.Option("--children", help="Also show the runs of the sub-agent sessions."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Show the session journal: marks, hand-overs, skips, and curation results."""
    given: str | None = _given("--session", session)
    handlers: CaptureHandlers = build_capture(cli_state(context).environment())

    async def read() -> CaptureRunListDto:
        identity: ResolvedIdentityDto = await _identity(handlers, given)
        query = ListCaptureRunsQuery(
            session_id=identity.session_id, limit=limit, include_children=children
        )
        return await handlers.runs.handle(query)

    output.emit(CaptureRunListResponse.model_validate(asyncio.run(read())))
