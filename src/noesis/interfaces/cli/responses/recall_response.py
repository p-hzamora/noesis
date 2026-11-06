"""`noesis notes recall` output."""

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


class RecallResponse(IRenderableResponse):
    """`noesis notes recall`: the digest, best first, with what was left out.

    Attributes:
        entries: The notes worth reading; empty when nothing relevant was found.
        considered: How many notes the search returned and the ranking looked at.
        omitted: How many of those are not in `entries` (past the limit or over the budget).
        backend: The implemented backend that produced the notes, which is `filesystem`
            after a fallback even when `obsidian-mcp` is configured.
    """

    entries: tuple[RecallEntryResponse, ...]
    considered: int
    omitted: int
    backend: SearchEngineEnum

    def render(self) -> str:
        if not self.entries:
            lines: list[str] = [NO_RELEVANT_NOTES]
        else:
            lines = []
            for entry in self.entries:
                dated: str = f"  ({entry.date})" if entry.date else ""
                lines.append(f"{entry.path}  [{entry.kind or 'note'}]  {entry.title}{dated}")
                if entry.snippet:
                    lines.append(f"    {entry.snippet}")
        lines.append(f"considered {self.considered}, omitted {self.omitted}")
        lines.append(f"backend: {self.backend}")
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
