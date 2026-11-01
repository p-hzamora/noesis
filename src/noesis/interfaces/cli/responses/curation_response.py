"""`noesis knowledge curate|retry` output."""

from noesis.utils import FrozenObject


class SkippedCandidateResponse(FrozenObject):
    """A candidate curation did not store, and why.

    Attributes:
        candidate: Short name of the candidate knowledge.
        reason: Why it was rejected.
    """

    candidate: str
    reason: str


class CurationResponse(FrozenObject):
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
