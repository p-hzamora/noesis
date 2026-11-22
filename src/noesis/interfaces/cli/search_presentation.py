"""Project resolution and search response mapping shared by `search` and `recall`."""

from enum import StrEnum
from pathlib import Path

import typer

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
        warnings=(*_warnings(result, key, space, source), *result.warnings),
    )
