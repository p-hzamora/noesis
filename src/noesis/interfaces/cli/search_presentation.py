"""Project resolution and search response mapping shared by `search` and `recall`."""

from enum import StrEnum
from pathlib import Path

from noesis.bounded_context.retrieval.application.dtos.record_search_dtos import (
    RecordSearchResultDto,
)
from noesis.bounded_context.retrieval.domain.enums import ProjectScopeEnum
from noesis.core.git_root import find_common_dir, repository_name
from noesis.interfaces.cli.responses import (
    SearchHitResponse,
    SearchIndexResponse,
    SearchResponse,
    SearchScopeResponse,
    SearchSemanticResponse,
)


class ProjectSourceEnum(StrEnum):
    """How the project of a search was chosen."""

    OPTION = "option"
    GIT_ROOT = "git_root"
    ALL_PROJECTS = "all_projects"
    NONE = "none"


def resolve_project(
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


def search_response(
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
