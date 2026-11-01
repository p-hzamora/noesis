"""`noesis capture runs` output."""

from noesis.utils import FrozenObject


class CaptureRunResponse(FrozenObject):
    """One journaled event of `noesis capture runs`.

    Attributes:
        at: When it happened (ISO 8601).
        outcome: Outcome value.
        detail: Human detail.
        reference: Brief file or other artefact, when there is one.
        result: Curation result read back from the reference, when available.
    """

    at: str
    outcome: str
    detail: str = ""
    reference: str | None = None
    result: dict[str, object] | None = None


class CaptureRunListResponse(FrozenObject):
    """`noesis capture runs`: the journal of one session, oldest first.

    Attributes:
        session_id: The session.
        runs: The entries.
    """

    session_id: str
    runs: tuple[CaptureRunResponse, ...]
