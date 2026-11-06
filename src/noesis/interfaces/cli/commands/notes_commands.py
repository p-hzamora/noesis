"""`noesis notes`: curate work briefs, retry parked ones, search, recall and list notes."""

import asyncio
import sys
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from noesis.bounded_context.notes.application.dtos import CurationResultDto, RejectedEntryDto
from noesis.bounded_context.notes.application.handlers.commands import (
    ApplyCurationCommand,
    CurateWorkBriefCommand,
    RetryParkedCurationCommand,
)
from noesis.bounded_context.notes.application.handlers.queries import (
    ListNotesQuery,
    ListParkedCurationsQuery,
    RecallNotesQuery,
    SearchNotesQuery,
)
from noesis.bounded_context.notes.domain.value_objects import (
    CurationDecision,
    NoteArea,
    NoteOriginEnum,
)
from noesis.bounded_context.notes.domain.value_objects.work_brief import SHORT_SESSION_LENGTH
from noesis.bounded_context.notes.infrastructure.outbound.curation.apply_input_schema import (
    parse_decisions_strict,
)
from noesis.core.git_root import find_common_dir, repository_name
from noesis.exceptions import (
    EmptyRecallTaskError,
    InvalidWorkBriefError,
    NotInGitRepositoryError,
)
from noesis.interfaces.cli import output
from noesis.interfaces.cli.bootstrap import NotesHandlers, build_apply, build_notes
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import (
    CurationPreviewResponse,
    CurationResponse,
    NoteListResponse,
    NoteSearchFallbackResponse,
    NoteSearchResponse,
    ParkedCurationListResponse,
    RecallFallbackResponse,
    RecallResponse,
)
from noesis.interfaces.cli.state import cli_state
from noesis.shared_kernel.contracts import WorkBriefContract

DEFAULT_ATTEMPTS: int = 2

notes_app: typer.Typer = typer.Typer(
    help="Curate work into notes, retry failed curations, search and list notes.",
    no_args_is_help=True,
)

AreaOption = Annotated[str | None, typer.Option("--area", help="Vault folder, e.g. repos/noesis.")]
RepoOption = Annotated[str | None, typer.Option("--repo", help="Shortcut for --area repos/<repo>.")]


def _handlers(context: typer.Context) -> NotesHandlers:
    return build_notes(cli_state(context).environment())


def _area(area: str | None, repo: str | None) -> str | None:
    return NoteArea.for_repository(repo).value if repo else area


def _warn(handlers: NotesHandlers) -> None:
    """Show adapter notices on stderr, which never breaks the JSON on stdout."""
    for notice in handlers.notices:
        sys.stderr.write(f"notice: {notice}\n")


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


@notes_app.command("curate")
def curate(
    context: typer.Context,
    brief_file: Annotated[
        Path, typer.Option("--brief-file", help="Work-brief JSON file.", dir_okay=False)
    ],
    max_attempts: Annotated[
        int, typer.Option("--max-attempts", min=1, help="Curator runs before giving up.")
    ] = (DEFAULT_ATTEMPTS),
    park: Annotated[
        bool, typer.Option("--park/--no-park", help="Park the brief when every attempt fails.")
    ] = True,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Judge and show the paths and outcomes without writing."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Ask the curator what in a work brief is worth keeping, then store it as auto notes."""
    command = CurateWorkBriefCommand(
        brief=_load_brief(brief_file),
        max_attempts=max_attempts,
        park_on_failure=park,
        dry_run=dry_run,
    )
    handlers = _handlers(context)
    stored: CurationResultDto = asyncio.run(handlers.curate.handle(command))
    _warn(handlers)
    output.emit(
        CurationPreviewResponse.model_validate(stored)
        if dry_run
        else CurationResponse.model_validate(stored)
    )


def _repository_area() -> NoteArea:
    """The area of the git repository the command runs in (a linked worktree uses its main repository).

    Raises:
        NotInGitRepositoryError: The working directory is outside any git repository.
    """
    common_dir: Path | None = find_common_dir(Path.cwd())
    if common_dir is None:
        raise NotInGitRepositoryError(
            f"{Path.cwd()} is not inside a git repository.",
            {"cwd": str(Path.cwd())},
            next_steps=["Run the command from inside the repository the notes belong to."],
        )
    return NoteArea.for_repository(repository_name(common_dir))


def _read_payload(source: str) -> tuple[str, RejectedEntryDto | None]:
    """The decisions text from a file or stdin (`-`), or why it cannot be read."""
    if source == "-":
        return sys.stdin.read(), None
    try:
        return Path(source).read_text(encoding="utf-8"), None
    except (OSError, UnicodeDecodeError) as error:
        return "", RejectedEntryDto(index=None, reason=f"cannot read {source}: {error}")


@notes_app.command("apply")
def apply(
    context: typer.Context,
    decisions_file: Annotated[
        str,
        typer.Option(
            "--decisions-file",
            help='JSON file with {"decisions": [...]} (same entries as the curator\'s answer); '
            "`-` reads stdin.",
        ),
    ],
    session: Annotated[
        str | None, typer.Option("--session", help="Session id recorded on the notes.")
    ] = None,
    commit: Annotated[
        list[str] | None,
        typer.Option("--commit", help="Commit SHA the notes come from (repeatable)."),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show the paths and outcomes without writing.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Store note drafts you wrote as auto notes, without calling the curator."""
    area: NoteArea = _repository_area()
    raw_payload, unreadable = _read_payload(decisions_file)
    decisions: tuple[CurationDecision, ...] = ()
    rejected: tuple[RejectedEntryDto, ...] = (unreadable,) if unreadable else ()
    if unreadable is None:
        decisions, rejected = parse_decisions_strict(raw_payload)
    command = ApplyCurationCommand(
        area=area,
        decisions=decisions,
        rejected=rejected,
        raw_payload=raw_payload,
        commits=tuple(commit or ()),
        session=session[:SHORT_SESSION_LENGTH] if session else None,
        dry_run=dry_run,
    )
    stored: CurationResultDto = asyncio.run(
        build_apply(cli_state(context).environment()).handle(command)
    )
    output.emit(
        CurationPreviewResponse.model_validate(stored)
        if dry_run
        else CurationResponse.model_validate(stored)
    )


@notes_app.command("retry")
def retry(
    context: typer.Context,
    ticket: Annotated[str, typer.Argument(help="Ticket from `noesis notes parked`.")],
    as_json: JsonOption = False,
) -> None:
    """Retry a parked curation once, in the foreground."""
    result = CurationResponse.model_validate(
        asyncio.run(_handlers(context).retry.handle(RetryParkedCurationCommand(ticket=ticket)))
    )
    output.emit(result)


@notes_app.command("parked")
def parked(context: typer.Context, as_json: JsonOption = False) -> None:
    """List work briefs whose curation failed and wait for `retry`."""
    result = ParkedCurationListResponse.model_validate(
        asyncio.run(_handlers(context).list_parked.handle(ListParkedCurationsQuery()))
    )
    output.emit(result)


@notes_app.command("search")
def search(
    context: typer.Context,
    text: Annotated[str, typer.Argument(help="Words to look for.")],
    area: AreaOption = None,
    repo: RepoOption = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    as_json: JsonOption = False,
) -> None:
    """Find notes by free text, best match first."""
    query = SearchNotesQuery(text=text, area=_area(area, repo), limit=limit)
    handlers = _handlers(context)
    found = NoteSearchResponse.model_validate(asyncio.run(handlers.search.handle(query)))
    if not handlers.notices:
        output.emit(found)
        return
    notice: str = handlers.notices[0]
    output.emit(NoteSearchFallbackResponse(notes=found.notes, backend=found.backend, notice=notice))


@notes_app.command("recall")
def recall(
    context: typer.Context,
    task: Annotated[str, typer.Argument(help="One sentence on what you are about to do.")],
    area: AreaOption = None,
    repo: RepoOption = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=20, help="Most entries.")] = 5,
    budget_tokens: Annotated[
        int,
        typer.Option(
            "--budget-tokens", min=0, help="Rough size cap of the digest; 0 is unlimited."
        ),
    ] = 1000,
    as_json: JsonOption = False,
) -> None:
    """List the notes worth reading before a task: kind, title, path, date and a snippet."""
    if not task.strip():
        raise EmptyRecallTaskError(
            "The task must not be empty.",
            next_steps=[
                'Pass one sentence about the task, for example: noesis notes recall "fix the login cache".'
            ],
        )
    scope: str | None = _area(area, repo)
    query = RecallNotesQuery(
        task=task,
        area=scope if scope else _repository_area().value,
        limit=limit,
        budget_tokens=budget_tokens,
    )
    handlers = _handlers(context)
    digest = RecallResponse.model_validate(asyncio.run(handlers.recall.handle(query)))
    if not handlers.notices:
        output.emit(digest)
        return
    notice: str = handlers.notices[0]
    output.emit(
        RecallFallbackResponse(
            entries=digest.entries,
            considered=digest.considered,
            omitted=digest.omitted,
            backend=digest.backend,
            notice=notice,
        )
    )


@notes_app.command("list")
def list_notes(
    context: typer.Context,
    area: AreaOption = None,
    repo: RepoOption = None,
    origin: Annotated[
        NoteOriginEnum | None, typer.Option("--origin", help="Only manual or auto notes.")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """List notes, optionally of one area and one origin."""
    query = ListNotesQuery(area=_area(area, repo), origin=origin)
    result = NoteListResponse.model_validate(
        asyncio.run(_handlers(context).list_notes.handle(query))
    )
    output.emit(result)
