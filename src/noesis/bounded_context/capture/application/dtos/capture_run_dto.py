"""Journal entries of a session."""

from noesis.shared_kernel.application.dtos import BaseDto


class CaptureRunDto(BaseDto):
    """One journaled event.

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


class CaptureRunListDto(BaseDto):
    """The journal of one session, oldest first.

    Attributes:
        session_id: The session.
        runs: The entries.
    """

    session_id: str
    runs: tuple[CaptureRunDto, ...]
