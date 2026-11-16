"""`noesis curate`: turn work briefs and written candidates into records of the knowledge store."""

import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from noesis.bounded_context.knowledge.application.dtos import (
    CurationResultDto,
    ParkedCurationDto,
    RejectedEntryDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.apply_curation_handler import (
    ApplyCurationCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.ingest_work_brief_handler import (
    IngestWorkBriefCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.retry_parked_curation_handler import (
    RetryParkedCurationCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_parked_curations_handler import (
    ListParkedCurationsQuery,
)
from noesis.bounded_context.knowledge.application.services.curation_runner import (
    RelatedLookupModeEnum,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    CurationCandidate,
    Key,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.curation import (
    parse_apply_payload,
)
from noesis.core import Environment
from noesis.core.git_root import find_common_dir, repository_name
from noesis.exceptions import (
    AppException,
    InvalidWorkBriefError,
    NotInGitRepositoryError,
)
from noesis.interfaces.cli import output
from noesis.interfaces.cli.actor import resolve_actor
from noesis.interfaces.cli.bootstrap import (
    CurationHandlers,
    build_parked_listing,
    open_curation,
    related_lookup_mode,
)
from noesis.interfaces.cli.bootstrap.retrieval_handlers_builder import trigger_index_sync
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import (
    CurateParkedItemResponse,
    CurateParkedResponse,
    CurateResponse,
    CurateRetryAllResponse,
    ErrorDetail,
    RetryTicketResponse,
)
from noesis.interfaces.cli.state import cli_state
from noesis.shared_kernel.contracts import WorkBriefContract

DEFAULT_ATTEMPTS: int = 2
STDIN_MARKER: str = "-"

curate_app: typer.Typer = typer.Typer(
    help="Curate work into records of the knowledge store, and retry what failed.",
    no_args_is_help=True,
)


def _usage(context: typer.Context, message: str, hint: str) -> typer.BadParameter:
    return typer.BadParameter(message, ctx=context, param_hint=hint)


async def _with_curation[T](
    environment: Environment, use: Callable[[CurationHandlers], Awaitable[T]]
) -> T:
    """Run `use` over the invocation's curation handlers; the Neo4j client closes afterwards."""
    async with open_curation(environment) as handlers:
        return await use(handlers)


def _load_brief(path: Path) -> WorkBriefContract:
    """Read and validate a work-brief file."""
    try:
        return WorkBriefContract.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise InvalidWorkBriefError(
            f"Cannot use {path} as a work brief: {str(error).splitlines()[0]}",
            {"brief_file": str(path)},
            next_steps=["Pass a JSON file that matches the work-brief contract (version 1)."],
        ) from error


def _project_key() -> str:
    """The key of the git repository the command runs in (a linked worktree uses its main one).

    Raises:
        NotInGitRepositoryError: The working directory is outside any git repository.
    """
    common_dir: Path | None = find_common_dir(Path.cwd())
    if common_dir is None:
        raise NotInGitRepositoryError(
            f"{Path.cwd()} is not inside a git repository.",
            {"cwd": str(Path.cwd())},
            next_steps=["Run the command from inside the repository the records belong to."],
        )
    return repository_name(common_dir)


def _read_payload(source: str) -> tuple[str, RejectedEntryDto | None]:
    """The payload text from a file or stdin (`-`), or why it cannot be read."""
    if source == STDIN_MARKER:
        return sys.stdin.read(), None
    try:
        return Path(source).read_text(encoding="utf-8"), None
    except (OSError, UnicodeDecodeError) as error:
        return "", RejectedEntryDto(index=None, reason=f"cannot read {source}: {error}")


def _error_detail(error: AppException) -> ErrorDetail:
    return ErrorDetail(
        code=error.error_code,
        title=error.error_title(),
        message=error.message,
        metadata=error.metadata,
        next_steps=list(error.next_steps),
    )


@curate_app.command("brief")
def brief(
    context: typer.Context,
    brief_file: Annotated[
        Path, typer.Option("--brief-file", help="Work-brief JSON file.", dir_okay=False)
    ],
    max_attempts: Annotated[
        int, typer.Option("--max-attempts", min=1, help="Curator runs before giving up.")
    ] = DEFAULT_ATTEMPTS,
    park: Annotated[
        bool,
        typer.Option("--park/--no-park", help="Park the brief when the curator keeps failing."),
    ] = True,
    no_related: Annotated[
        bool,
        typer.Option(
            "--no-related", help="Do not look up related records (the curator gets none)."
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Judge and show the outcomes; write and park nothing."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Ask the curator what in a work brief is worth keeping, then store it as records.

    Records are proposals and experiences with the brief's commits and session as sources.
    Running it again on the same work writes nothing new.
    """
    contract: WorkBriefContract = _load_brief(brief_file)
    env: Environment = cli_state(context).environment()
    command = IngestWorkBriefCommand(
        brief=contract,
        space_key=Key(value=env.knowledge.knowledge_space),
        max_attempts=max_attempts,
        park_on_failure=park,
        dry_run=dry_run,
        related_lookup=RelatedLookupModeEnum.OFF if no_related else related_lookup_mode(env),
    )
    result: CurationResultDto = asyncio.run(
        _with_curation(env, lambda handlers: handlers.ingest.handle(command))
    )
    if not dry_run and not result.replayed:
        trigger_index_sync(env)
    output.emit(CurateResponse.model_validate(result, from_attributes=True))


@curate_app.command("apply")
def apply(
    context: typer.Context,
    decisions_file: Annotated[
        str,
        typer.Option(
            "--decisions-file",
            help='JSON file with {"candidates": [...]} (the curator\'s entry shape); `-` reads stdin.',
        ),
    ],
    session: Annotated[
        str | None,
        typer.Option(
            "--session",
            help="Session id recorded as a source (default: the session of the running harness).",
        ),
    ] = None,
    commit: Annotated[
        list[str] | None,
        typer.Option("--commit", help="Commit SHA the records come from (repeatable)."),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show the outcomes; write and keep nothing.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Store candidates you wrote as records, without calling the curator.

    Any flawed entry fails the whole call before anything is written; the redacted payload is
    kept so it can be fixed and applied again.
    """
    project_key: str = _project_key()
    env: Environment = cli_state(context).environment()
    actor: Actor = resolve_actor(env.identity)
    session_id: str | None = session or actor.session
    if session_id is None:
        raise _usage(
            context,
            "No session id: pass --session, or run inside an agent harness that exposes one.",
            "--session",
        )
    if actor.kind is ActorKindEnum.AGENT and actor.session is None:
        actor = actor.model_copy(update={"session": session_id})
    raw_payload, unreadable = _read_payload(decisions_file)
    candidates: tuple[CurationCandidate, ...] = ()
    rejected: tuple[RejectedEntryDto, ...] = (unreadable,) if unreadable else ()
    if unreadable is None:
        parsed = parse_apply_payload(raw_payload)
        candidates, rejected = parsed.candidates, parsed.rejected
    command = ApplyCurationCommand(
        space_key=Key(value=env.knowledge.knowledge_space),
        candidates=candidates,
        rejected=rejected,
        project_key=project_key,
        session=session_id,
        commits=tuple(commit or ()),
        actor=actor,
        raw_payload=raw_payload,
        dry_run=dry_run,
    )
    result: CurationResultDto = asyncio.run(
        _with_curation(env, lambda handlers: handlers.apply.handle(command))
    )
    if not dry_run and not result.replayed:
        trigger_index_sync(env)
    output.emit(CurateResponse.model_validate(result, from_attributes=True))


@curate_app.command("retry")
def retry(
    context: typer.Context,
    ticket: Annotated[
        str | None, typer.Argument(help="Ticket from `noesis curate parked`.")
    ] = None,
    all_tickets: Annotated[
        bool, typer.Option("--all", help="Retry every parked ticket (needs --yes to run).")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", help="With --all: run the retries instead of listing them.")
    ] = False,
    as_json: JsonOption = False,
) -> int:
    """Retry a parked curation from the stage it failed at.

    A saved plan is never judged again, and steps already written return their original ids.
    `--all` without `--yes` only lists what it would retry.
    """
    if (ticket is None) == (not all_tickets):
        raise _usage(context, "Give a ticket, or --all.", "TICKET")
    env: Environment = cli_state(context).environment()
    if ticket is not None:
        command = RetryParkedCurationCommand(
            ticket=ticket,
            space_key=Key(value=env.knowledge.knowledge_space),
            related_lookup=related_lookup_mode(env),
        )
        single: CurationResultDto = asyncio.run(
            _with_curation(env, lambda handlers: handlers.retry.handle(command))
        )
        if not single.replayed:
            trigger_index_sync(env)
        output.emit(CurateResponse.model_validate(single, from_attributes=True))
        return 0
    parked: tuple[ParkedCurationDto, ...] = asyncio.run(
        build_parked_listing(env).handle(ListParkedCurationsQuery())
    )
    if not yes:
        output.emit(
            CurateRetryAllResponse(
                executed=False,
                tickets=tuple(_pending(item) for item in parked),
            )
        )
        return 0
    report: CurateRetryAllResponse = asyncio.run(_retry_all(env, parked))
    output.emit(report)
    return 1 if report.failed else 0


def _pending(item: ParkedCurationDto) -> RetryTicketResponse:
    return RetryTicketResponse(
        ticket=item.ticket,
        repository=item.repository,
        stage=item.stage,
        reason=item.reason,
        outcome="pending",
    )


async def _retry_all(
    environment: Environment, parked: tuple[ParkedCurationDto, ...]
) -> CurateRetryAllResponse:
    """Retry each parked ticket in turn; a ticket that fails again does not stop the others."""
    results: list[RetryTicketResponse] = []
    async with open_curation(environment) as handlers:
        for item in parked:
            command = RetryParkedCurationCommand(
                ticket=item.ticket,
                space_key=Key(value=environment.knowledge.knowledge_space),
                related_lookup=related_lookup_mode(environment),
            )
            try:
                result: CurationResultDto = await handlers.retry.handle(command)
            except AppException as error:
                results.append(
                    _pending(item).model_copy(
                        update={"outcome": "failed", "error": _error_detail(error)}
                    )
                )
                continue
            results.append(
                _pending(item).model_copy(
                    update={
                        "outcome": "retried",
                        "result": CurateResponse.model_validate(result, from_attributes=True),
                    }
                )
            )
    trigger_index_sync(environment)
    return CurateRetryAllResponse(
        executed=True,
        tickets=tuple(results),
        failed=sum(1 for item in results if item.outcome == "failed"),
    )


@curate_app.command("parked")
def parked(context: typer.Context, as_json: JsonOption = False) -> None:
    """List submissions whose curation failed and wait for `retry`, oldest first.

    It reads only the local inbox, so it works with the store down.
    """
    env: Environment = cli_state(context).environment()
    listed: tuple[ParkedCurationDto, ...] = asyncio.run(
        build_parked_listing(env).handle(ListParkedCurationsQuery())
    )
    output.emit(
        CurateParkedResponse(
            parked=tuple(
                CurateParkedItemResponse.model_validate(item, from_attributes=True)
                for item in listed
            )
        )
    )
