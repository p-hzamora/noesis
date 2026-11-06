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
        session_id: The session the entry belongs to (set when reading, so merged journals
            of a parent and its children stay apart).
    """

    at: str
    outcome: str
    detail: str = ""
    reference: str | None = None
    result: dict[str, object] | None = None
    session_id: str = ""


class CaptureRunListDto(BaseDto):
    """The journal of one session, oldest first.

    Attributes:
        session_id: The session.
        runs: The entries.
        children: Child sessions whose journals are merged in (empty unless asked for).
    """

    session_id: str
    runs: tuple[CaptureRunDto, ...]
    children: tuple[str, ...] = ()
