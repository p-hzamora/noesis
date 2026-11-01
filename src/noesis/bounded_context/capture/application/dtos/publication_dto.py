"""Receipt of handing a work brief over."""

from noesis.shared_kernel.application.dtos import BaseDto


class PublicationDto(BaseDto):
    """Whether the brief left, and where it went.

    Attributes:
        published: Whether the hand-over started.
        reference: Brief file or other artefact for the journal.
        detail: Human detail, e.g. the error when it did not start.
    """

    published: bool
    reference: str | None = None
    detail: str = ""
