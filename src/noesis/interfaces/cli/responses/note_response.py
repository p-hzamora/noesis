"""`noesis notes list|search` output."""

from noesis.shared_kernel.enums import SearchEngineEnum
from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse


class NoteResponse(FrozenObject):
    """A note as listed by `noesis notes list|search`.

    Attributes:
        id: Stable note id (ULID), unchanged when the file moves.
        scope: `repo:<name>` or `topic:<name>`.
        path: Source-relative path.
        title: Note title.
        kind: Note kind name.
        origin: `manual` or `auto`.
        updated: Last update date (ISO), when known.
        snippet: Start of the first section, for context.
    """

    id: str
    scope: str
    path: str
    title: str
    kind: str
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
            f"{note.path}  [{note.origin} {note.kind}]  {note.title}" for note in self.notes
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
