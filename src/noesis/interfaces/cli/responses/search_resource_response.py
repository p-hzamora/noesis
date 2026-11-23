"""`noesis search` output beyond the record list: requirements, resources, next actions, briefing.

`SearchResponse` stays the record-only shape (`--no-resources`); the classes here add keys to
it and never change one it has.
"""

from datetime import datetime

from noesis.bounded_context.retrieval.application.dtos.briefing_dtos import (
    BriefingItemDto,
    RecommendedToolDto,
)
from noesis.utils import FrozenObject

from .recall_response import RecallRecordResponse
from .search_response import SearchIndexResponse, SearchResponse

_BRIEFING_SECTIONS: tuple[str, ...] = (
    "constraints",
    "decisions",
    "context",
    "unconfirmed",
    "unsupported",
)


class SearchRequirementResponse(FrozenObject):
    """One requirement facet and its coverage.

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


class SearchResourceWhyResponse(FrozenObject):
    """Why a resource is listed.

    Attributes:
        matched: Facets its name, purpose or capabilities mention.
        channels: `catalog_text`, `recommends` or `prerequisite`.
    """

    matched: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()


class SearchResourceDiscoveredResponse(FrozenObject):
    """Where the artifact was seen installed.

    Attributes:
        runtimes: Runtimes in which it is installed.
        observed_at: When this search looked; null when no runtime was looked at.
    """

    runtimes: tuple[str, ...] = ()
    observed_at: datetime | None = None


class SearchRefinementResponse(FrozenObject):
    """A memory that refines a resource.

    Attributes:
        ref: `record:<id>@<revision>`.
        authority: The memory's authority label.
    """

    ref: str
    authority: str


class SearchResourceResponse(FrozenObject):
    """One skill, agent, CLI tool or MCP server to consult.

    Attributes:
        ref: `catalog:<kind>:<name>`.
        catalog_id: The catalog entry; null when the artifact is not cataloged yet.
        kind: `skill`, `agent`, `cli_tool` or `mcp_server`.
        name: Entry or artifact name.
        revision: Head revision; null when not cataloged.
        manifest_digest: Hash of the manifest seen, if any.
        cataloged: False for an installed artifact that was never synced.
        origin: `registered` or `discovered`.
        purpose: What it is for.
        why: Why it is listed.
        requires: Refs of its declared prerequisites.
        discovered: Where it was seen installed.
        available: Runtime -> `available|unavailable|unknown`; null when not checked.
        endorsement: `user`, `project`, `proposed` or `none`.
        recommended_by: Ids of `recommends` assertions (history, not endorsement).
        refined_by: Memories that refine it within the scope.
        load_action: The action that loads it.
        load_order: Its position in the load order, prerequisites first.
    """

    ref: str
    catalog_id: str | None
    kind: str
    name: str
    revision: int | None
    manifest_digest: str | None
    cataloged: bool
    origin: str
    purpose: str
    why: SearchResourceWhyResponse
    requires: tuple[str, ...]
    discovered: SearchResourceDiscoveredResponse
    available: dict[str, str] | None
    endorsement: str
    recommended_by: tuple[str, ...]
    refined_by: tuple[SearchRefinementResponse, ...]
    load_action: str
    load_order: int


class SearchNextActionResponse(FrozenObject):
    """One step: a closed action and a canonical ref, never text to execute.

    Attributes:
        order: 1-based position.
        action: `load_skill`, `use_agent`, `use_cli_tool`, `use_mcp_server` or `read_record`.
        ref: `catalog:<kind>:<name>` or `record:<id>@<revision>`.
    """

    order: int
    action: str
    ref: str


class SearchCatalogIndexResponse(FrozenObject):
    """Whether the matched installed artifacts are cataloged.

    Attributes:
        synced: No returned installed artifact lacks a catalog entry.
        unsynced_installed: How many returned artifacts are installed but not cataloged.
    """

    synced: bool
    unsynced_installed: int


class SearchResourceIndexResponse(SearchIndexResponse):
    """The index freshness plus the catalog state.

    Attributes:
        catalog: Catalog sync state; null when the catalog channel did not run.
    """

    catalog: SearchCatalogIndexResponse | None = None


class SearchBriefingResponse(FrozenObject):
    """The sections of `recall`, in today's semantics.

    Attributes:
        synthesis: `briefing`, `digest` or `no_evidence`.
        records: Evidence considered, without bodies.
        constraints: Grounded constraints.
        decisions: Grounded decisions.
        context: Grounded context.
        unconfirmed: Claims backed only by proposed records.
        unsupported: Claims the evidence does not back.
        capabilities: Review and catalog capability states.
        tools: Recommended tools with observed availability.
        tools_state: `checked`, `not_verified` or `not_available`.
    """

    synthesis: str
    records: tuple[RecallRecordResponse, ...]
    constraints: tuple[BriefingItemDto, ...]
    decisions: tuple[BriefingItemDto, ...]
    context: tuple[BriefingItemDto, ...]
    unconfirmed: tuple[BriefingItemDto, ...]
    unsupported: tuple[BriefingItemDto, ...]
    capabilities: dict[str, str]
    tools: tuple[RecommendedToolDto, ...]
    tools_state: str


class SearchBriefedResponse(SearchResponse):
    """`SearchResponse` plus the briefing, for `--no-resources --briefing`.

    Attributes:
        briefing: The briefing sections; null when none was requested.
    """

    briefing: SearchBriefingResponse | None = None

    def render(self) -> str:
        lines: list[str] = [super().render()]
        if self.briefing is not None:
            lines.append(f"briefing: {self.briefing.synthesis}")
            for name in _BRIEFING_SECTIONS:
                for item in getattr(self.briefing, name):
                    cited: str = ", ".join(
                        f"{citation.record_id}@{citation.revision}" for citation in item.citations
                    )
                    lines.append(f"  {name}: {item.text} [{cited}]")
        return "\n".join(lines)


class ResourceSearchResponse(SearchBriefedResponse):
    """`noesis search`: records plus the resources to consult and how well they cover the task.

    Attributes:
        index: Freshness of the answer and the catalog state.
        requirements: One per facet, with coverage.
        resources: In load order, prerequisites first.
        next_actions: Typed steps, prerequisites first, then records to read.
    """

    index: SearchResourceIndexResponse
    requirements: tuple[SearchRequirementResponse, ...] = ()
    resources: tuple[SearchResourceResponse, ...] = ()
    next_actions: tuple[SearchNextActionResponse, ...] = ()

    def render(self) -> str:
        lines: list[str] = []
        for requirement in self.requirements:
            backing: str = (
                f"  <- {', '.join(requirement.supported_by)}" if requirement.supported_by else ""
            )
            lines.append(f"need [{requirement.coverage}] {requirement.id}{backing}")
        for resource in self.resources:
            states: str = (
                ""
                if resource.available is None
                else "; " + ", ".join(f"{k}: {v}" for k, v in resource.available.items())
            )
            lines.append(
                f"{resource.load_order}. {resource.kind} {resource.name}  "
                f"(endorsement: {resource.endorsement}{states}"
                f"{'' if resource.cataloged else '; not cataloged'})"
            )
            lines.append(f"   {resource.purpose}")
        for action in self.next_actions:
            lines.append(f"next {action.order}: {action.action} {action.ref}")
        lines.append(super().render())
        return "\n".join(lines)
