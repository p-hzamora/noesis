"""`noesis knowledge`: curate work briefs, retry parked ones, search and list notes."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from noesis.bounded_context.knowledge.application.handlers.commands import (
    CurateWorkBriefCommand,
    RetryParkedCurationCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries import (
    ListNotesQuery,
    ListParkedCurationsQuery,
    SearchNotesQuery,
)
from noesis.bounded_context.knowledge.domain.value_objects import NoteArea, NoteOriginEnum
from noesis.exceptions import (
    InvalidWorkBriefError,
)
from noesis.interfaces.cli.bootstrap import KnowledgeHandlers, build_knowledge
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.output import emit
from noesis.interfaces.cli.responses import (
    CurationResponse,
    NoteListResponse,
    ParkedCurationListResponse,
)
from noesis.interfaces.cli.state import cli_state
from noesis.shared_kernel.contracts import WorkBriefContract

DEFAULT_ATTEMPTS: int = 2

knowledge_app: typer.Typer = typer.Typer(
    help="Curate work into notes, retry failed curations, search and list notes.",
    no_args_is_help=True,
)

AreaOption = Annotated[str | None, typer.Option("--area", help="Vault folder, e.g. repos/noesis.")]
RepoOption = Annotated[str | None, typer.Option("--repo", help="Shortcut for --area repos/<repo>.")]


def _handlers(context: typer.Context) -> KnowledgeHandlers:
    return build_knowledge(cli_state(context).environment())


def _area(area: str | None, repo: str | None) -> str | None:
    return NoteArea.for_repository(repo).value if repo else area


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


def _format_result(result: CurationResponse) -> str:
    lines: list[str] = [
        f"{result.repository}: {len(result.created)} created, {len(result.updated)} updated, "
        f"{len(result.skipped)} skipped"
    ]
    lines += [f"  created {path}" for path in result.created]
    lines += [f"  updated {path}" for path in result.updated]
    lines += [f"  skipped {item.candidate}: {item.reason}" for item in result.skipped]
    return "\n".join(lines)


def _format_notes(result: NoteListResponse) -> str:
    if not result.notes:
        return "no notes"
    return "\n".join(
        f"{note.path}  [{note.origin} {note.kind}]  {note.title}" for note in result.notes
    )


def _format_parked(result: ParkedCurationListResponse) -> str:
    if not result.parked:
        return "nothing parked"
    return "\n".join(
        f"{item.ticket}  {item.repository}@{item.head[:8]}  {item.error}" for item in result.parked
    )


@knowledge_app.command("curate")
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
    as_json: JsonOption = False,
) -> None:
    """Ask the curator what in a work brief is worth keeping, and store it as auto notes."""
    command: CurateWorkBriefCommand = CurateWorkBriefCommand(
        brief=_load_brief(brief_file), max_attempts=max_attempts, park_on_failure=park
    )
    result: CurationResponse = CurationResponse.model_validate(
        asyncio.run(_handlers(context).curate.handle(command))
    )
    emit(result, _format_result)


@knowledge_app.command("retry")
def retry(
    context: typer.Context,
    ticket: Annotated[str, typer.Argument(help="Ticket from `noesis knowledge parked`.")],
    as_json: JsonOption = False,
) -> None:
    """Retry a parked curation once, in the foreground."""
    result: CurationResponse = CurationResponse.model_validate(
        asyncio.run(_handlers(context).retry.handle(RetryParkedCurationCommand(ticket=ticket)))
    )
    emit(result, _format_result)


@knowledge_app.command("parked")
def parked(context: typer.Context, as_json: JsonOption = False) -> None:
    """List work briefs whose curation failed and wait for `retry`."""
    result: ParkedCurationListResponse = ParkedCurationListResponse.model_validate(
        asyncio.run(_handlers(context).list_parked.handle(ListParkedCurationsQuery()))
    )
    emit(result, _format_parked)


@knowledge_app.command("search")
def search(
    context: typer.Context,
    text: Annotated[str, typer.Argument(help="Words to look for.")],
    area: AreaOption = None,
    repo: RepoOption = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    as_json: JsonOption = False,
) -> None:
    """Find notes by free text, best match first."""
    query: SearchNotesQuery = SearchNotesQuery(text=text, area=_area(area, repo), limit=limit)
    result: NoteListResponse = NoteListResponse.model_validate(
        asyncio.run(_handlers(context).search.handle(query))
    )
    emit(result, _format_notes)


@knowledge_app.command("list")
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
    query: ListNotesQuery = ListNotesQuery(area=_area(area, repo), origin=origin)
    result: NoteListResponse = NoteListResponse.model_validate(
        asyncio.run(_handlers(context).list_notes.handle(query))
    )
    emit(result, _format_notes)
