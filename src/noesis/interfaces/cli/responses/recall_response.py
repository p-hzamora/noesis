"""`noesis notes recall` output."""

from typing import Literal

from noesis.shared_kernel.enums import SearchEngineEnum
from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse

NO_RELEVANT_NOTES: str = "no relevant notes"


class RecallEntryResponse(FrozenObject):
    """A note worth reading, as listed by `noesis notes recall`; never its body.

    Attributes:
        kind: Note kind value; None for a note outside the noesis layout.
        title: Note title.
        path: Vault-relative path; read that file for the full note.
        date: Last update date (ISO), when known.
        snippet: Start of the first section, possibly shortened to fit the budget.
    """

    kind: str | None
    title: str
    path: str
    date: str | None
    snippet: str


class BriefingItemResponse(FrozenObject):
    """One statement of the briefing and the notes that back it.

    Attributes:
        text: The statement.
        sources: Paths of the notes that support it (for an inference: the notes it builds on).
    """

    text: str
    sources: tuple[str, ...]


class RecallBriefingResponse(FrozenObject):
    """The briefing an agent wrote from the notes it read, grounded in note paths.

    Attributes:
        summary: What matters most for the task.
        constraints: Rules the work must respect; each cites at least one note.
        decisions: Choices already made; each cites at least one note.
        gotchas: Traps and past failures; each cites at least one note.
        context: Other useful background; each cites at least one note.
        open_questions: Points the notes leave unresolved.
        inferences: The agent's own conclusions, which no note states.
        unsupported: Statements set aside because no note that was read backs them.
        not_covered: Aspects of the task the notes say nothing about.
        model: Model that answered, as its runtime reported it; None when unknown.
        markdown: The whole briefing as a Markdown document.
    """

    summary: str
    constraints: tuple[BriefingItemResponse, ...]
    decisions: tuple[BriefingItemResponse, ...]
    gotchas: tuple[BriefingItemResponse, ...]
    context: tuple[BriefingItemResponse, ...]
    open_questions: tuple[BriefingItemResponse, ...]
    inferences: tuple[BriefingItemResponse, ...]
    unsupported: tuple[BriefingItemResponse, ...]
    not_covered: tuple[str, ...]
    model: str | None
    markdown: str


class RecallResponse(IRenderableResponse):
    """`noesis notes recall`: a briefing for the task, or the ranked digest with `--no-synthesis`.

    Attributes:
        entries: The notes read for the briefing, or the notes worth reading in a digest;
            best first, empty when nothing relevant was found.
        considered: How many notes the search returned and the ranking looked at.
        omitted: How many of those are not in `entries` (past the limit or over the budget).
        backend: The implemented backend that produced the notes, which is `filesystem`
            after a fallback even when `obsidian-mcp` is configured.
        synthesis: `briefing` (an agent wrote `briefing`), `no_evidence` (nothing found, no
            agent ran) or `digest` (`--no-synthesis`).
        briefing: The briefing; null unless `synthesis` is `briefing`.
        warnings: What limited the briefing (notes unreadable, text cut, secrets masked).
    """

    entries: tuple[RecallEntryResponse, ...]
    considered: int
    omitted: int
    backend: SearchEngineEnum
    synthesis: Literal["briefing", "no_evidence", "digest"]
    briefing: RecallBriefingResponse | None
    warnings: tuple[str, ...]

    def render(self) -> str:
        if self.briefing is not None:
            lines: list[str] = [self.briefing.markdown.rstrip("\n"), ""]
            if self.briefing.model:
                lines.append(f"model: {self.briefing.model}")
        elif not self.entries:
            lines = [NO_RELEVANT_NOTES]
        else:
            lines = []
            for entry in self.entries:
                dated: str = f"  ({entry.date})" if entry.date else ""
                lines.append(f"{entry.path}  [{entry.kind or 'note'}]  {entry.title}{dated}")
                if entry.snippet:
                    lines.append(f"    {entry.snippet}")
        lines.append(f"considered {self.considered}, omitted {self.omitted}")
        lines.append(f"backend: {self.backend}")
        lines += [f"warning: {warning}" for warning in self.warnings]
        return "\n".join(lines)


class RecallFallbackResponse(RecallResponse):
    """`noesis notes recall` when Obsidian could not answer and files were searched instead.

    Only this variant carries `notice`.

    Attributes:
        notice: Why the results come from files.
    """

    notice: str

    def render(self) -> str:
        return f"{super().render()}\nnotice: {self.notice}"
