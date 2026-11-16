"""Recall's public evidence and grounded sections, without internal search machinery."""

from noesis.bounded_context.retrieval.application.dtos.briefing_dtos import (
    BriefingItemDto,
    EvidenceDto,
    RecommendedToolDto,
)

from .i_renderable_response import IRenderableResponse
from .search_response import SearchIndexResponse, SearchScopeResponse


class RecallRecordResponse(EvidenceDto):
    """Public evidence metadata; body is presented only through grounded sections."""

    body: None = None


class RecallResponse(IRenderableResponse):
    """A read-only scoped briefing or digest."""

    synthesis: str
    scope: SearchScopeResponse
    records: tuple[RecallRecordResponse, ...]
    constraints: tuple[BriefingItemDto, ...]
    decisions: tuple[BriefingItemDto, ...]
    context: tuple[BriefingItemDto, ...]
    unconfirmed: tuple[BriefingItemDto, ...]
    unsupported: tuple[BriefingItemDto, ...]
    tools: tuple[RecommendedToolDto, ...]
    tools_state: str
    index: SearchIndexResponse
    capabilities: dict[str, str]
    warnings: tuple[str, ...]
    next_steps: tuple[str, ...]

    def render(self) -> str:
        lines = [self.synthesis]
        for record in self.records:
            label = (record.status or record.authority).upper()
            lines.append(f"[{label}] {record.title or record.type} ({record.id}@{record.revision})")
            if record.superseded_by:
                lines.append(f"  superseded by: {', '.join(record.superseded_by)}")
            if record.omitted_reason:
                lines.append(f"  omitted: {record.omitted_reason}")
        for name in ("constraints", "decisions", "context", "unconfirmed", "unsupported"):
            for item in getattr(self, name):
                citations = ", ".join(
                    f"{citation.record_id}@{citation.revision}" for citation in item.citations
                )
                lines.append(f"{name}: {item.text} [{citations}]")
        for tool in self.tools:
            lines.append(
                f"tool {tool.catalog_id}: {'usable' if tool.usable else 'not verified or unavailable'} ({tool.endorsement})"
            )
            for runtime in tool.runtimes:
                for entry in runtime.entries:
                    lines.append(f"  {runtime.runtime}: {entry.status} ({entry.reason})")
        lines.append(
            f"semantic: {self.index.semantic.state}; pending changes: {self.index.pending_changes}"
        )
        lines.extend(f"warning: {warning}" for warning in self.warnings)
        lines.extend(f"next: {step}" for step in self.next_steps)
        return "\n".join(lines)
