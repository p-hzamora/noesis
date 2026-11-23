"""`noesis search`: find knowledge and experience records of the active space."""

import asyncio
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from noesis.bounded_context.retrieval.application.dtos.record_search_dtos import (
    RecordSearchRequestDto,
)
from noesis.bounded_context.retrieval.application.dtos.search_dtos import (
    DEFAULT_RESOURCE_LIMIT,
    MAX_RESOURCE_LIMIT,
    UnifiedSearchRequestDto,
    UnifiedSearchResultDto,
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
from noesis.interfaces.cli.runtime_resolution import parse_runtimes, resolve_runtimes
from noesis.interfaces.cli.search_presentation import (
    invocation_project,
    resolve_project,
    unified_search_response,
)
from noesis.interfaces.cli.state import cli_state

DEFAULT_LIMIT: int = 10
MAX_LIMIT: int = 50


MAX_NEED_CHARS: int = 64


class BriefingOption(StrEnum):
    """What briefing `search` adds to the answer."""

    NONE = "none"
    DIGEST = "digest"
    SYNTHESIS = "synthesis"


class SearchTypeOption(StrEnum):
    """The record types search returns."""

    KNOWLEDGE = "knowledge"
    EXPERIENCE = "experience"


def search(
    context: typer.Context,
    query: Annotated[str, typer.Argument(help="What to look for.")],
    target_root: Annotated[
        Path | None,
        typer.Option(
            "--target-root",
            file_okay=False,
            help="Root of the existing or planned target repository.",
        ),
    ] = None,
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
    need: Annotated[
        list[str] | None,
        typer.Option(
            "--need",
            help="A facet the task needs, 1 to 64 characters (repeatable); default: query terms.",
        ),
    ] = None,
    runtime: Annotated[
        list[str] | None,
        typer.Option("--runtime", help="claude-code or codex (repeatable); default: your session."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=MAX_LIMIT, help="Most record hits to return (1 to 50)."),
    ] = DEFAULT_LIMIT,
    resource_limit: Annotated[
        int,
        typer.Option(
            "--resource-limit",
            min=0,
            max=MAX_RESOURCE_LIMIT,
            help="Most resources to select before their prerequisites (0 to 20).",
        ),
    ] = DEFAULT_RESOURCE_LIMIT,
    no_resources: Annotated[
        bool,
        typer.Option("--no-resources", help="Records only: skip skills, agents and tools."),
    ] = False,
    briefing: Annotated[
        BriefingOption,
        typer.Option(
            "--briefing",
            help="none (default), digest (no model) or synthesis (a model summarises the records).",
        ),
    ] = BriefingOption.NONE,
    budget_chars: Annotated[
        int | None,
        typer.Option(
            "--budget-chars", min=1, help="Evidence budget of the briefing, in characters."
        ),
    ] = None,
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
    """Find what to consult for a task: records, skills, agents and tools, with coverage and order."""
    if not query.strip():
        raise typer.BadParameter("Give a non-empty query.", ctx=context, param_hint="QUERY")
    needs: tuple[str, ...] = tuple(item.strip() for item in need or ())
    if any(not item or len(item) > MAX_NEED_CHARS for item in needs):
        raise typer.BadParameter(
            f"Each need is 1 to {MAX_NEED_CHARS} characters.", ctx=context, param_hint="--need"
        )
    parse_runtimes(runtime or [])
    key, source = resolve_project(project, all_projects, target_root)
    env: Environment = cli_state(context).environment()
    if semantic and semantic_mode(env) is SemanticModeEnum.OFF:
        raise typer.BadParameter(
            "--semantic needs NOESIS_RETRIEVAL_SEMANTIC_MODE=resident or per-call (it is off).",
            ctx=context,
            param_hint="--semantic",
        )
    space: str = env.knowledge.knowledge_space
    runtimes = resolve_runtimes(runtime or [], env.identity)

    async def run(handlers: RetrievalHandlers, space_id: str) -> UnifiedSearchResultDto:
        if handlers.unified_search is None:
            raise RuntimeError("Unified search handler was not wired")
        request = UnifiedSearchRequestDto(
            records=RecordSearchRequestDto(
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
            ),
            needs=needs,
            runtimes=tuple(item.value for item in runtimes),
            resource_limit=resource_limit,
            include_resources=not no_resources,
            briefing=briefing.value,
            budget_chars=budget_chars,
        )
        return await handlers.unified_search.handle(request)

    result: UnifiedSearchResultDto = asyncio.run(
        with_retrieval(env, run, semantic_opt_in=semantic or require_semantic)
    )
    output.emit(
        unified_search_response(
            result, space=space, key=key, source=source, invoked_from=invocation_project()
        )
    )
