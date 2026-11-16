"""`noesis search`: find knowledge and experience records of the active space."""

import asyncio
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from noesis.bounded_context.retrieval.application.dtos.record_search_dtos import (
    RecordSearchRequestDto,
    RecordSearchResultDto,
)
from noesis.bounded_context.retrieval.domain.enums import ProjectScopeEnum
from noesis.core import Environment
from noesis.core.git_root import find_common_dir, repository_name
from noesis.interfaces.cli import output
from noesis.interfaces.cli.bootstrap.retrieval_handlers_builder import (
    RetrievalHandlers,
    with_retrieval,
)
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import (
    SearchHitResponse,
    SearchIndexResponse,
    SearchResponse,
    SearchScopeResponse,
    SearchSemanticResponse,
)
from noesis.interfaces.cli.state import cli_state

DEFAULT_LIMIT: int = 10
MAX_LIMIT: int = 50


class SearchTypeOption(StrEnum):
    """The record types search returns."""

    KNOWLEDGE = "knowledge"
    EXPERIENCE = "experience"


class ProjectSourceEnum(StrEnum):
    """How the project of a search was chosen."""

    OPTION = "option"
    GIT_ROOT = "git_root"
    ALL_PROJECTS = "all_projects"
    NONE = "none"


def _resolve_project(
    project: str | None, all_projects: bool
) -> tuple[str | None, ProjectSourceEnum]:
    """The project key and where it came from: option, git root, all projects or none."""
    if all_projects:
        return None, ProjectSourceEnum.ALL_PROJECTS
    if project is not None:
        return project, ProjectSourceEnum.OPTION
    common_dir: Path | None = find_common_dir(Path.cwd())
    if common_dir is None:
        return None, ProjectSourceEnum.NONE
    return repository_name(common_dir), ProjectSourceEnum.GIT_ROOT


def _warnings(result: RecordSearchResultDto, key: str | None, space: str) -> tuple[str, ...]:
    if result.project_scope is not ProjectScopeEnum.SPACE_WIDE_ONLY:
        return ()
    reason: str = (
        "not in a git repository" if key is None else f"project {key} not found in space {space}"
    )
    return (f"no project resolved ({reason}); searched space-wide records only",)


def _response(
    result: RecordSearchResultDto,
    *,
    space: str,
    key: str | None,
    source: ProjectSourceEnum,
) -> SearchResponse:
    return SearchResponse(
        scope=SearchScopeResponse(
            space=space,
            project=key,
            project_source=source.value,
            space_wide_only=result.project_scope is ProjectScopeEnum.SPACE_WIDE_ONLY,
        ),
        hits=tuple(
            SearchHitResponse(
                id=hit.record_id,
                type=hit.record_type,
                subtype=hit.subtype,
                title=hit.title,
                revision=hit.revision,
                status=hit.status,
                authority=hit.authority.value,
                project=hit.project_id,
                sources=tuple(kind.value for kind in hit.sources),
                revised_at=hit.revised_at,
                rank=hit.rank,
            )
            for hit in result.hits
        ),
        index=SearchIndexResponse(
            pending_changes=result.pending_changes,
            stale_hits=result.stale_hits,
            semantic=SearchSemanticResponse(state=result.semantic_state.value),
            filter_shortfall=result.filter_shortfall,
        ),
        warnings=(*_warnings(result, key, space), *result.warnings),
    )


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
    as_json: JsonOption = False,
) -> None:
    """Find records by text and shared sources, best first, labelled by authority."""
    if not query.strip():
        raise typer.BadParameter("Give a non-empty query.", ctx=context, param_hint="QUERY")
    if project is not None and all_projects:
        raise typer.BadParameter(
            "--project and --all-projects cannot be used together.",
            ctx=context,
            param_hint="--project",
        )
    env: Environment = cli_state(context).environment()
    key, source = _resolve_project(project, all_projects)
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

    result: RecordSearchResultDto = asyncio.run(with_retrieval(env, run))
    output.emit(_response(result, space=space, key=key, source=source))
