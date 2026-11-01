"""Result of curating one work brief."""

from noesis.shared_kernel.application.dtos import BaseDto


class SkippedCandidateDto(BaseDto):
    """A candidate that was not stored, and why: the main signal for tuning the curator.

    Attributes:
        candidate: Short name of the candidate knowledge.
        reason: Why it was rejected.
    """

    candidate: str
    reason: str


class CurationResultDto(BaseDto):
    """What curation stored.

    Attributes:
        repository: Repository the brief came from.
        created: Paths of new notes.
        updated: Paths of revised auto notes.
        skipped: Rejected candidates with reasons.
    """

    repository: str
    created: tuple[str, ...]
    updated: tuple[str, ...]
    skipped: tuple[SkippedCandidateDto, ...]
