"""`noesis capture runs` output."""

from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse


class CaptureRunResponse(FrozenObject):
    """One journaled event of `noesis capture runs`.

    Attributes:
        at: When it happened (ISO 8601).
        outcome: Outcome value.
        detail: Human detail.
        reference: Brief file or other artefact, when there is one.
        result: Curation result read back from the reference, when available.
        session_id: The session the entry belongs to.
    """

    at: str
    outcome: str
    detail: str = ""
    reference: str | None = None
    result: dict[str, object] | None = None
    session_id: str = ""


class CaptureRunListResponse(IRenderableResponse):
    """`noesis capture runs`: the journal of one session, oldest first.

    Attributes:
        session_id: The session.
        runs: The entries.
        children: Child sessions whose runs are merged in.
    """

    session_id: str
    runs: tuple[CaptureRunResponse, ...]
    children: tuple[str, ...] = ()

    def render(self) -> str:
        if not self.runs:
            return f"session {self.session_id}: nothing journaled yet"
        lines: list[str] = []
        for run in self.runs:
            owner: str = f"[{run.session_id}] " if self.children else ""
            lines.append(f"{run.at}  {run.outcome:<20} {owner}{run.detail}")
            if run.reference:
                lines.append(f"{'':21}brief: {run.reference}")
            if run.result is not None:
                lines.append(f"{'':21}result: {'ok' if run.result.get('ok') else 'failed'}")
        return "\n".join(lines)
