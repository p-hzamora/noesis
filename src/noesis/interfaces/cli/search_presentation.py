"""Project resolution and search response mapping shared by `search` and `recall`."""

from enum import StrEnum
from pathlib import Path

import typer

from noesis.bounded_context.retrieval.application.dtos.briefing_dtos import RecallResultDto
from noesis.bounded_context.retrieval.application.dtos.record_search_dtos import (
    RecordSearchResultDto,
)
from noesis.bounded_context.retrieval.application.dtos.search_dtos import UnifiedSearchResultDto
from noesis.bounded_context.retrieval.domain.enums import ProjectScopeEnum
from noesis.core.git_root import find_common_dir, repository_name
from noesis.interfaces.cli.responses import (
    SearchHitResponse,
    SearchIndexResponse,
    SearchResponse,
    SearchScopeResponse,
    SearchSemanticResponse,
)
from noesis.interfaces.cli.responses.recall_response import RecallRecordResponse
from noesis.interfaces.cli.responses.search_resource_response import (
    ResourceSearchResponse,
    SearchBriefedResponse,
    SearchBriefingResponse,
    SearchCatalogIndexResponse,
    SearchNextActionResponse,
    SearchRequirementResponse,
    SearchResourceIndexResponse,
    SearchResourceResponse,
)


class ProjectSourceEnum(StrEnum):
    """How the project of a search was chosen."""

    OPTION = "option"
    GIT_ROOT = "git_root"
    ALL_PROJECTS = "all_projects"
    NONE = "none"
    TARGET_ROOT = "target_root"


def resolve_project(
    project: str | None, all_projects: bool, target_root: Path | None = None
) -> tuple[str | None, ProjectSourceEnum]:
    """Resolve the selected project using the same repository identity as record capture."""
    if sum((project is not None, all_projects, target_root is not None)) > 1:
        raise typer.BadParameter("Choose only one of --project, --all-projects and --target-root.")
    if target_root is not None:
        # A planned project within an existing checkout must not inherit its parent's identity.
        root = target_root.expanduser().resolve()
        common = find_common_dir(root)
        if common is not None and ((root / ".git").exists() or common == root):
            return repository_name(common), ProjectSourceEnum.TARGET_ROOT
        return None, ProjectSourceEnum.TARGET_ROOT
    if all_projects:
        return None, ProjectSourceEnum.ALL_PROJECTS
    if project is not None:
        return project, ProjectSourceEnum.OPTION
    common_dir: Path | None = find_common_dir(Path.cwd())
    if common_dir is None:
        return None, ProjectSourceEnum.NONE
    return repository_name(common_dir), ProjectSourceEnum.GIT_ROOT


def invocation_project() -> str | None:
    """The project detected from the working directory, independent of any scope override."""
    common_dir: Path | None = find_common_dir(Path.cwd())
    return None if common_dir is None else repository_name(common_dir)


def _warnings(
    result: RecordSearchResultDto, key: str | None, space: str, source: ProjectSourceEnum
) -> tuple[str, ...]:
    if result.project_scope is not ProjectScopeEnum.SPACE_WIDE_ONLY:
        return ()
    if source is ProjectSourceEnum.TARGET_ROOT and key is None:
        return ("target has no repository identity; searched space-wide records only",)
    reason: str = (
        "not in a git repository" if key is None else f"project {key} not found in space {space}"
    )
    return (f"no project resolved ({reason}); searched space-wide records only",)


def search_response(
    result: RecordSearchResultDto,
    *,
    space: str,
    key: str | None,
    source: ProjectSourceEnum,
    invoked_from: str | None = None,
) -> SearchResponse:
    return SearchResponse(
        scope=SearchScopeResponse(
            space=space,
            project=key,
            project_source=source.value,
            space_wide_only=result.project_scope is ProjectScopeEnum.SPACE_WIDE_ONLY,
            invocation_project=invoked_from,
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
        warnings=(*_warnings(result, key, space, source), *result.warnings),
    )


def _briefing(result: RecallResultDto) -> SearchBriefingResponse:
    return SearchBriefingResponse(
        synthesis=result.synthesis,
        records=tuple(
            RecallRecordResponse.model_validate(record.model_dump(exclude={"body"}))
            for record in result.records
        ),
        constraints=result.constraints,
        decisions=result.decisions,
        context=result.context,
        unconfirmed=result.unconfirmed,
        unsupported=result.unsupported,
        capabilities=result.capabilities,
        tools=result.tools,
        tools_state=result.tools_state,
    )


def unified_search_response(
    result: UnifiedSearchResultDto,
    *,
    space: str,
    key: str | None,
    source: ProjectSourceEnum,
    invoked_from: str | None = None,
) -> SearchResponse:
    """The record-only shape for `--no-resources`; with resources, the same keys plus the new ones."""
    base: SearchResponse = search_response(
        result.records, space=space, key=key, source=source, invoked_from=invoked_from
    )
    warnings: tuple[str, ...] = (*base.warnings, *result.warnings)
    briefing: SearchBriefingResponse | None = (
        None if result.briefing is None else _briefing(result.briefing)
    )
    if not result.resources_included:
        if briefing is None:
            return base
        return SearchBriefedResponse(
            scope=base.scope, hits=base.hits, index=base.index, warnings=warnings, briefing=briefing
        )
    return ResourceSearchResponse(
        scope=base.scope,
        hits=base.hits,
        index=SearchResourceIndexResponse(
            **base.index.model_dump(),
            catalog=None
            if result.catalog is None
            else SearchCatalogIndexResponse.model_validate(result.catalog),
        ),
        warnings=warnings,
        briefing=briefing,
        requirements=tuple(
            SearchRequirementResponse.model_validate(item) for item in result.requirements
        ),
        resources=tuple(
            SearchResourceResponse.model_validate(item.model_dump(mode="python"))
            for item in result.resources
        ),
        next_actions=tuple(
            SearchNextActionResponse(order=item.order, action=item.action.value, ref=item.ref)
            for item in result.next_actions
        ),
    )
