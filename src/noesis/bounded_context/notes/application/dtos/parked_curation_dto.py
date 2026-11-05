"""Briefs whose curation failed and wait for a manual retry."""

from noesis.shared_kernel.application.dtos import BaseDto


class ParkedCurationDto(BaseDto):
    """One parked brief.

    Attributes:
        ticket: Id to pass to `noesis notes retry`.
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


class ParkedCurationListDto(BaseDto):
    """Every parked brief, oldest first.

    Attributes:
        parked: The parked briefs.
    """

    parked: tuple[ParkedCurationDto, ...]
