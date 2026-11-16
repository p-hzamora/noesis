"""`noesis search`: find knowledge and experience records of the active space."""

import asyncio
from enum import StrEnum
from typing import Annotated

import typer

from noesis.bounded_context.retrieval.application.dtos.record_search_dtos import (
    RecordSearchRequestDto,
    RecordSearchResultDto,
)
from noesis.bounded_context.retrieval.domain.enums import SemanticModeEnum
from noesis.core import Environment
from noesis.interfaces.cli import output
from noesis.interfaces.cli.bootstrap.retrieval_handlers_builder import (
    RetrievalHandlers,
    semantic_mode,
    with_retrieval,
)
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.search_presentation import resolve_project, search_response
from noesis.interfaces.cli.state import cli_state

DEFAULT_LIMIT: int = 10
MAX_LIMIT: int = 50


class SearchTypeOption(StrEnum):
    """The record types search returns."""

    KNOWLEDGE = "knowledge"
    EXPERIENCE = "experience"


def search(
    context: typer.Context,
    query: Annotated[str, typer.Argument(help="What to look for.")],
    project: Annotated[
        str | None,
        typer.Option(
            "--project",
            help="Project key (default: the name of the git repository of the working directory).",
        ),
    ] = None,
    all_projects: Annotated[
        bool, typer.Option("--all-projects", help="Search every project (not with --project).")
    ] = False,
    tag: Annotated[
        list[str] | None, typer.Option("--tag", help="Only records with this tag (repeatable).")
    ] = None,
    record_type: Annotated[
        list[SearchTypeOption] | None,
        typer.Option("--type", help="Only this record type (repeatable; default both)."),
    ] = None,
    status: Annotated[
        list[str] | None,
        typer.Option("--status", help="Only this status (repeatable; default all but retracted)."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=MAX_LIMIT, help="Most hits to return (1 to 50)."),
    ] = DEFAULT_LIMIT,
    include_stale: Annotated[
        bool, typer.Option("--include-stale", help="Also list hits at an old revision.")
    ] = False,
    require_semantic: Annotated[
        bool,
        typer.Option("--require-semantic", help="Fail unless a semantic index can answer."),
    ] = False,
    semantic: Annotated[
        bool,
        typer.Option(
            "--semantic",
            help="Use semantic search in per-call mode (loads the model in this process).",
        ),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Find records by text, shared sources and (when available) meaning, labelled by authority."""
    if not query.strip():
        raise typer.BadParameter("Give a non-empty query.", ctx=context, param_hint="QUERY")
    if project is not None and all_projects:
        raise typer.BadParameter(
            "--project and --all-projects cannot be used together.",
            ctx=context,
            param_hint="--project",
        )
    env: Environment = cli_state(context).environment()
    if semantic and semantic_mode(env) is SemanticModeEnum.OFF:
        raise typer.BadParameter(
            "--semantic needs NOESIS_RETRIEVAL_SEMANTIC_MODE=resident or per-call (it is off).",
            ctx=context,
            param_hint="--semantic",
        )
    key, source = resolve_project(project, all_projects)
    space: str = env.knowledge.knowledge_space

    async def run(handlers: RetrievalHandlers, space_id: str) -> RecordSearchResultDto:
        request = RecordSearchRequestDto(
            text=query,
            space_id=space_id,
            project_key=key,
            all_projects=all_projects,
            tags=tuple(tag or ()),
            record_types=tuple(item.value for item in record_type or ()),
            statuses=tuple(status or ()),
            limit=limit,
            include_stale=include_stale,
            require_semantic=require_semantic,
        )
        return await handlers.search.handle(request)

    result: RecordSearchResultDto = asyncio.run(
        with_retrieval(env, run, semantic_opt_in=semantic or require_semantic)
    )
    output.emit(search_response(result, space=space, key=key, source=source))
