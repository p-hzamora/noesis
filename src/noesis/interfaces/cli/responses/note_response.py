"""`noesis notes list|search` output."""

from noesis.shared_kernel.enums import SearchEngineEnum
from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse


class NoteResponse(FrozenObject):
    """A note as listed by `noesis notes list|search`.

    Attributes:
        path: Vault-relative path.
        title: Note title.
        kind: Note kind value; None for a note outside the noesis layout (found by Obsidian search).
        origin: `manual` or `auto`.
        updated: Last update date (ISO), when known.
        snippet: Start of the first section, for context.
    """

    path: str
    title: str
    kind: str | None
    origin: str
    updated: str | None
    snippet: str


class NoteListResponse(IRenderableResponse):
    """`noesis notes list|search`: notes, best match first for searches.

    Attributes:
        notes: The notes.
    """

    notes: tuple[NoteResponse, ...]

    def render(self) -> str:
        if not self.notes:
            return "no notes"
        return "\n".join(
            f"{note.path}  [{note.origin} {note.kind or 'note'}]  {note.title}"
            for note in self.notes
        )


class NoteSearchResponse(NoteListResponse):
    """`noesis notes search`: notes plus the backend that actually answered.

    Attributes:
        backend: The implemented backend that produced `notes`, which is
            `filesystem` after a fallback even when `obsidian-mcp` is configured.
    """

    backend: SearchEngineEnum

    def render(self) -> str:
        return f"{super().render()}\nbackend: {self.backend}"


class NoteSearchFallbackResponse(NoteSearchResponse):
    """`noesis notes search` when Obsidian could not answer and files were searched instead.

    Only this variant carries `notice`.

    Attributes:
        notice: Why the results come from files.
    """

    notice: str

    def render(self) -> str:
        return f"{super().render()}\nnotice: {self.notice}"
