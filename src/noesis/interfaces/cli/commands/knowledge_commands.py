"""`noesis knowledge`: curate work briefs, retry parked ones, search and list notes."""

import asyncio
import sys
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
from noesis.interfaces.cli import output
from noesis.interfaces.cli.bootstrap import KnowledgeHandlers, build_knowledge
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import (
    CurationResponse,
    NoteListResponse,
    NoteSearchFallbackResponse,
    NoteSearchResponse,
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


def _warn(handlers: KnowledgeHandlers) -> None:
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
    command = CurateWorkBriefCommand(
        brief=_load_brief(brief_file), max_attempts=max_attempts, park_on_failure=park
    )
    handlers = _handlers(context)
    result = CurationResponse.model_validate(asyncio.run(handlers.curate.handle(command)))
    _warn(handlers)
    output.emit(result)


@knowledge_app.command("retry")
def retry(
    context: typer.Context,
    ticket: Annotated[str, typer.Argument(help="Ticket from `noesis knowledge parked`.")],
    as_json: JsonOption = False,
) -> None:
    """Retry a parked curation once, in the foreground."""
    result = CurationResponse.model_validate(
        asyncio.run(_handlers(context).retry.handle(RetryParkedCurationCommand(ticket=ticket)))
    )
    output.emit(result)


@knowledge_app.command("parked")
def parked(context: typer.Context, as_json: JsonOption = False) -> None:
    """List work briefs whose curation failed and wait for `retry`."""
    result = ParkedCurationListResponse.model_validate(
        asyncio.run(_handlers(context).list_parked.handle(ListParkedCurationsQuery()))
    )
    output.emit(result)


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
    query = SearchNotesQuery(text=text, area=_area(area, repo), limit=limit)
    handlers = _handlers(context)
    found = NoteSearchResponse.model_validate(asyncio.run(handlers.search.handle(query)))
    if not handlers.notices:
        output.emit(found)
        return
    notice: str = handlers.notices[0]
    output.emit(NoteSearchFallbackResponse(notes=found.notes, backend=found.backend, notice=notice))


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
    query = ListNotesQuery(area=_area(area, repo), origin=origin)
    result = NoteListResponse.model_validate(
        asyncio.run(_handlers(context).list_notes.handle(query))
    )
    output.emit(result)
