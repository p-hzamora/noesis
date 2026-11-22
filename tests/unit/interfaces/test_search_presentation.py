"""Search scope mapping reports the invoking project next to the scoped one."""

from noesis.bounded_context.retrieval.application.dtos.record_search_dtos import (
    RecordSearchResultDto,
)
from noesis.bounded_context.retrieval.domain.enums import ProjectScopeEnum, SemanticStateEnum
from noesis.interfaces.cli.search_presentation import ProjectSourceEnum, search_response


def _result() -> RecordSearchResultDto:
    return RecordSearchResultDto(
        hits=(),
        pending_changes=0,
        stale_hits=0,
        semantic_state=SemanticStateEnum.ABSENT,
        filter_shortfall=False,
        project_scope=ProjectScopeEnum.SPACE_WIDE_ONLY,
        project_id=None,
    )


def test_scope_reports_invocation_project_when_target_root_overrides() -> None:
    response = search_response(
        _result(),
        space="personal",
        key=None,
        source=ProjectSourceEnum.TARGET_ROOT,
        invoked_from="noesis",
    )

    assert response.scope.project is None
    assert response.scope.project_source == "target_root"
    assert response.scope.invocation_project == "noesis"


def test_scope_invocation_project_defaults_to_none() -> None:
    response = search_response(_result(), space="personal", key=None, source=ProjectSourceEnum.NONE)

    assert response.scope.invocation_project is None
