"""Derived review states: effective status and authority."""

from noesis.bounded_context.knowledge.domain.value_objects import RecordStatusEnum
from noesis.bounded_context.knowledge.domain.value_objects.enums import AuthorityLabelEnum

_AUTHORITY: dict[RecordStatusEnum | None, AuthorityLabelEnum] = {
    None: AuthorityLabelEnum.NOT_REVIEWABLE,
    RecordStatusEnum.RETRACTED: AuthorityLabelEnum.RETRACTED,
    RecordStatusEnum.SUPERSEDED: AuthorityLabelEnum.SUPERSEDED,
    RecordStatusEnum.PROPOSED: AuthorityLabelEnum.PROPOSED,
    RecordStatusEnum.ACCEPTED: AuthorityLabelEnum.AUTHORITATIVE,
}


def effective_status_of(
    stored: RecordStatusEnum | None, *, superseded_by_accepted: bool
) -> RecordStatusEnum | None:
    """Status a reader should see.

    Args:
        stored: The stored status; None for types without status.
        superseded_by_accepted: An accepted `supersedes` assertion has the record as object.

    Returns:
        None for types without status; `superseded` when targeted by an accepted `supersedes`,
        whatever the stored status says; else the stored status.
    """
    if stored is None:
        return None
    return RecordStatusEnum.SUPERSEDED if superseded_by_accepted else stored


def authority_of(effective: RecordStatusEnum | None) -> AuthorityLabelEnum:
    """The authority label of an effective status."""
    return _AUTHORITY[effective]
