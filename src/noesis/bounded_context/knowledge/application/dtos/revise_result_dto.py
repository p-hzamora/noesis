"""Result of revising knowledge."""

from noesis.shared_kernel.application.dtos import BaseDto


class ReviseResultDto(BaseDto):
    """The new head revision.

    Attributes:
        record_id: The revised record.
        revision: The new head revision number.
        status: Status of the record (`proposed`).
        space_id: Space it lives in.
        replayed: True when the idempotency key was already used and nothing was written.
    """

    record_id: str
    revision: int
    status: str
    space_id: str
    replayed: bool = False
