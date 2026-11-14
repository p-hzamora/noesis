"""Result of capturing a record."""

from noesis.shared_kernel.application.dtos import BaseDto


class CaptureResultDto(BaseDto):
    """The record a capture created, or the one an earlier identical capture created.

    Attributes:
        record_id: The record's id.
        record_type: `knowledge` or `experience`.
        revision: Head revision (knowledge); None for an experience.
        status: `proposed` (knowledge); None for an experience.
        space_id: Space it lives in.
        project_id: Its project, when any.
        replayed: True when the idempotency key was already used and nothing was written.
    """

    record_id: str
    record_type: str
    revision: int | None = None
    status: str | None = None
    space_id: str
    project_id: str | None = None
    replayed: bool = False
