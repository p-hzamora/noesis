"""Search request, hit and result."""

from datetime import datetime

from pydantic import Field

from noesis.shared_kernel.contracts.knowledge import GraphNeighbourContract
from noesis.utils import FrozenObject

from ...domain.enums import (
    AuthorityTierEnum,
    CandidateKindEnum,
    ProjectScopeEnum,
    SearchableRecordTypeEnum,
    SemanticStateEnum,
)


class RecordSearchRequestDto(FrozenObject):
    """One search.

    Attributes:
        text: The query.
        space_id: The active space.
        project_key: Key of the project to prefer, or null.
        all_projects: Search every project.
        tags: Labels a record must all carry.
        record_types: `knowledge` and/or `experience`; empty means both.
        statuses: Stored statuses to keep; empty means every status but `retracted`.
        limit: Most hits returned, 1..50.
        include_stale: Keep records a source found at an older revision (they are still counted).
        require_semantic: Fail when the semantic source is absent or unavailable.
    """

    text: str
    space_id: str
    project_key: str | None = None
    all_projects: bool = False
    tags: tuple[str, ...] = ()
    record_types: tuple[SearchableRecordTypeEnum, ...] = ()
    statuses: tuple[str, ...] = ()
    limit: int = Field(ge=1, le=50)
    include_stale: bool = False
    require_semantic: bool = False


class RecordSearchHitDto(FrozenObject):
    """One hit.

    Attributes:
        record_id: ULID of the record.
        record_type: `knowledge` or `experience`.
        subtype: The record's subtype.
        title: Head-revision title; null for an Experience.
        revision: Head revision; null for an Experience.
        status: Stored status; null for an Experience.
        authority: The authority tier.
        project_id: The record's project id; null when space-wide.
        sources: Candidate kinds that found it, each once, in the order lexical, graph, semantic.
        revised_at: When the head revision was created (UTC).
        rank: 1-based position in the returned order.
    """

    record_id: str
    record_type: str
    subtype: str | None
    title: str | None
    revision: int | None
    status: str | None
    authority: AuthorityTierEnum
    project_id: str | None
    sources: tuple[CandidateKindEnum, ...]
    revised_at: datetime
    rank: int
    discovery: tuple[GraphNeighbourContract, ...] = ()
    warnings: tuple[str, ...] = ()


class RecordSearchResultDto(FrozenObject):
    """The answer of a search or a similar-records query.

    Attributes:
        hits: The hits in rank order.
        pending_changes: Largest lag between the change feed head and a projection cursor.
        stale_hits: Candidates found at an older revision.
        semantic_state: What the semantic source contributed.
        filter_shortfall: Fewer than `limit` hits survived the filters even after the retry.
        project_scope: Which projects were searched.
        project_id: The project applied, else null.
    """

    hits: tuple[RecordSearchHitDto, ...]
    pending_changes: int
    stale_hits: int
    semantic_state: SemanticStateEnum
    filter_shortfall: bool
    project_scope: ProjectScopeEnum
    project_id: str | None

    warnings: tuple[str, ...] = ()
