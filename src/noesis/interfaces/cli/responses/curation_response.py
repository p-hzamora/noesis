"""`noesis knowledge curate|retry` output."""

from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse


class SkippedCandidateResponse(FrozenObject):
    """A candidate curation did not store, and why.

    Attributes:
        candidate: Short name of the candidate knowledge.
        reason: Why it was rejected.
    """

    candidate: str
    reason: str


class CurationResponse(IRenderableResponse):
    """`noesis knowledge curate|retry`: what curation stored.

    Attributes:
        repository: Repository the brief came from.
        created: Paths of new notes.
        updated: Paths of revised auto notes.
        skipped: Rejected candidates with reasons.
    """

    repository: str
    created: tuple[str, ...]
    updated: tuple[str, ...]
    skipped: tuple[SkippedCandidateResponse, ...]

    def render(self) -> str:
        lines: list[str] = [
            f"{self.repository}: {len(self.created)} created, {len(self.updated)} updated, "
            f"{len(self.skipped)} skipped"
        ]
        lines += [f"  created {path}" for path in self.created]
        lines += [f"  updated {path}" for path in self.updated]
        lines += [f"  skipped {item.candidate}: {item.reason}" for item in self.skipped]
        return "\n".join(lines)
