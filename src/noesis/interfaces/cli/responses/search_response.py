"""`noesis search` output."""

from datetime import datetime

from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse


class SearchScopeResponse(FrozenObject):
    """Where the search looked.

    Attributes:
        space: Key of the active space.
        project: The project key applied or asked for; None when no key was resolved.
        project_source: `option`, `target_root`, `git_root`, `all_projects` or `none`.
        space_wide_only: True when only space-wide records were searched.
        invocation_project: The project detected from the working directory, even when
            `--target-root`, `--project` or `--all-projects` scopes the search elsewhere.
    """

    space: str
    project: str | None = None
    project_source: str
    space_wide_only: bool
    invocation_project: str | None = None


class SearchHitResponse(FrozenObject):
    """One record found.

    Attributes:
        id: Record id.
        type: `knowledge` or `experience`.
        subtype: The record's subtype.
        title: Head-revision title; None for an experience.
        revision: Head revision; None for an experience.
        status: Stored status; None for an experience.
        authority: Authority tier label.
        project: Project id; None when space-wide.
        sources: Candidate kinds that found it (`lexical`, `graph`, `semantic`).
        revised_at: When the record last changed.
        rank: 1-based position in the answer.
    """

    id: str
    type: str
    subtype: str | None = None
    title: str | None = None
    revision: int | None = None
    status: str | None = None
    authority: str
    project: str | None = None
    sources: tuple[str, ...] = ()
    revised_at: datetime
    rank: int


class SearchSemanticResponse(FrozenObject):
    """State of the semantic source.

    Attributes:
        state: `absent`, `ready`, `lagging` or `unavailable`.
    """

    state: str


class SearchIndexResponse(FrozenObject):
    """Freshness of the answer.

    Attributes:
        pending_changes: Largest number of changes a projection has yet to apply.
        stale_hits: Hits dropped (or flagged) for being at an old revision.
        semantic: State of the semantic source.
        filter_shortfall: True when fewer hits than the limit exist after filtering.
    """

    pending_changes: int
    stale_hits: int
    semantic: SearchSemanticResponse
    filter_shortfall: bool


class SearchResponse(IRenderableResponse):
    """`noesis search`: ranked records with their scope and freshness.

    Attributes:
        scope: Where the search looked.
        hits: The records, best first.
        index: Freshness of the answer.
        warnings: Plain-English notices.
    """

    scope: SearchScopeResponse
    hits: tuple[SearchHitResponse, ...]
    index: SearchIndexResponse
    warnings: tuple[str, ...] = ()

    def render(self) -> str:
        lines: list[str] = []
        for hit in self.hits:
            label: str = hit.title or f"{hit.type} {hit.subtype or ''}".strip()
            lines.append(f"{hit.rank}. [{hit.authority}] {label}  ({hit.type} {hit.id})")
        if not self.hits:
            lines.append("no records found")
        scope: str = self.scope.project or (
            "all projects" if self.scope.project_source == "all_projects" else "no project"
        )
        lines.append(
            f"scope: {scope}{' (space-wide only)' if self.scope.space_wide_only else ''}; "
            f"semantic: {self.index.semantic.state}; pending changes: {self.index.pending_changes}"
        )
        if self.index.stale_hits:
            lines.append(f"stale hits: {self.index.stale_hits}")
        if self.index.filter_shortfall:
            lines.append("fewer hits than the limit matched the filters")
        lines += [f"warning: {warning}" for warning in self.warnings]
        return "\n".join(lines)
