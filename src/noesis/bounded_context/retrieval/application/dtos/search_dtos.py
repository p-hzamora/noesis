"""The unified search request and result: records, resources, requirements and next actions."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from noesis.utils import FrozenObject

from ...domain.enums import NextActionEnum
from .briefing_dtos import RecallResultDto
from .record_search_dtos import RecordSearchRequestDto, RecordSearchResultDto

type Need = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
type SearchRuntime = Literal["claude-code", "codex"]
DEFAULT_RESOURCE_LIMIT: int = 8
MAX_RESOURCE_LIMIT: int = 20


class UnifiedSearchRequestDto(FrozenObject):
    """One unified search.

    Attributes:
        records: The record search; `limit` keeps its meaning (record hits only).
        needs: Requirement facets named by the caller; empty means salient query terms.
        runtimes: Runtimes checked for availability and discovery; empty when none resolved.
        resource_limit: Resources selected before prerequisite expansion, 0..20.
        include_resources: False skips the catalog channel entirely (records only).
        briefing: `none`, `digest` (recall without a model) or `synthesis` (recall).
        budget_chars: Briefing evidence budget; the configured one when None.
    """

    records: RecordSearchRequestDto
    needs: tuple[Need, ...] = ()
    runtimes: tuple[SearchRuntime, ...] = ()
    resource_limit: int = Field(default=DEFAULT_RESOURCE_LIMIT, ge=0, le=MAX_RESOURCE_LIMIT)
    include_resources: bool = True
    briefing: Literal["none", "digest", "synthesis"] = "none"
    budget_chars: int | None = Field(default=None, ge=1)


class RequirementDto(FrozenObject):
    """One requirement facet and how well the answer covers it.

    Attributes:
        id: The facet.
        source: `need` or `query`.
        coverage: `covered`, `partial`, `missing` or `unknown`.
        supported_by: Refs of the resources and records that back it.
    """

    id: str
    source: str
    coverage: str
    supported_by: tuple[str, ...] = ()


class RefinementDto(FrozenObject):
    """A memory that refines a resource.

    Attributes:
        ref: `record:<id>@<revision>`.
        authority: The memory's authority label.
    """

    ref: str
    authority: str


class ResourceDiscoveryDto(FrozenObject):
    """Where the artifact was seen installed, independent of endorsement.

    Attributes:
        runtimes: Requested runtimes in which it is installed.
        observed_at: When this search looked; None when no runtime was looked at.
    """

    runtimes: tuple[str, ...] = ()
    observed_at: datetime | None = None


class ResourceWhyDto(FrozenObject):
    """Why a resource is in the answer.

    Attributes:
        matched: Requirement facets its name, purpose or capabilities mention.
        channels: `catalog_text`, `recommends` or `prerequisite`.
    """

    matched: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()


class SearchResourceDto(FrozenObject):
    """One skill, agent, CLI tool or MCP server to consult."""

    ref: str
    catalog_id: str | None
    kind: str
    name: str
    revision: int | None
    manifest_digest: str | None
    cataloged: bool
    origin: str
    purpose: str
    why: ResourceWhyDto
    requires: tuple[str, ...]
    discovered: ResourceDiscoveryDto
    available: dict[str, str] | None
    endorsement: str
    recommended_by: tuple[str, ...]
    refined_by: tuple[RefinementDto, ...]
    load_action: NextActionEnum
    load_order: int


class NextActionDto(FrozenObject):
    """One step for the caller; the action is a closed value and the ref a canonical ref."""

    order: int
    action: NextActionEnum
    ref: str


class CatalogIndexDto(FrozenObject):
    """Whether the matched installed artifacts are in the catalog.

    Attributes:
        synced: No matched installed artifact lacks a catalog entry.
        unsynced_installed: Returned artifacts that are installed but not cataloged.
    """

    synced: bool
    unsynced_installed: int


class UnifiedSearchResultDto(FrozenObject):
    """The answer of a unified search.

    Attributes:
        records: The record pipeline's result, unchanged.
        resources_included: False when the catalog channel was skipped (`include_resources`).
        requirements: One per facet.
        resources: In load order, prerequisites first.
        next_actions: Typed steps, prerequisites first, then records to read.
        catalog: Catalog sync state; None when the catalog channel did not run.
        briefing: The recall result when a briefing was requested.
        warnings: Notices added by the resource, briefing and semantic channels.
    """

    records: RecordSearchResultDto
    resources_included: bool = True
    requirements: tuple[RequirementDto, ...] = ()
    resources: tuple[SearchResourceDto, ...] = ()
    next_actions: tuple[NextActionDto, ...] = ()
    catalog: CatalogIndexDto | None = None
    briefing: RecallResultDto | None = None
    warnings: tuple[str, ...] = ()
