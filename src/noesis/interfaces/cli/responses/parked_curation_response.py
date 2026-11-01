"""`noesis knowledge parked` output."""

from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse


class ParkedCurationResponse(FrozenObject):
    """One parked brief of `noesis knowledge parked`.

    Attributes:
        ticket: Id to pass to `noesis knowledge retry`.
        repository: Repository of the brief.
        head: Newest commit of the brief.
        parked_at: When it was parked (ISO).
        error: Why the last attempt failed.
    """

    ticket: str
    repository: str
    head: str
    parked_at: str
    error: str


class ParkedCurationListResponse(IRenderableResponse):
    """`noesis knowledge parked`: every parked brief, oldest first.

    Attributes:
        parked: The parked briefs.
    """

    parked: tuple[ParkedCurationResponse, ...]

    def render(self) -> str:
        if not self.parked:
            return "nothing parked"
        return "\n".join(
            f"{item.ticket}  {item.repository}@{item.head[:8]}  {item.error}"
            for item in self.parked
        )
