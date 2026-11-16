"""The authority tier of a hit and the order of tiers."""

from collections.abc import Mapping
from types import MappingProxyType

from ..enums import AuthorityTierEnum

_TIER_ORDER: Mapping[AuthorityTierEnum, int] = MappingProxyType(
    {
        AuthorityTierEnum.AUTHORITATIVE: 0,
        AuthorityTierEnum.EXPERIENCE: 1,
        AuthorityTierEnum.PROPOSED: 2,
        AuthorityTierEnum.UNREVIEWED: 2,
        AuthorityTierEnum.SUPERSEDED: 3,
        AuthorityTierEnum.RETRACTED: 4,
    }
)
_BY_STATUS: Mapping[str, AuthorityTierEnum] = MappingProxyType(
    {
        "accepted": AuthorityTierEnum.AUTHORITATIVE,
        "proposed": AuthorityTierEnum.PROPOSED,
        "superseded": AuthorityTierEnum.SUPERSEDED,
        "retracted": AuthorityTierEnum.RETRACTED,
    }
)
_BY_REVIEW_AUTHORITY: Mapping[str, AuthorityTierEnum] = MappingProxyType(
    {
        "authoritative": AuthorityTierEnum.AUTHORITATIVE,
        "proposed": AuthorityTierEnum.PROPOSED,
        "superseded": AuthorityTierEnum.SUPERSEDED,
        "retracted": AuthorityTierEnum.RETRACTED,
        "not_reviewable": AuthorityTierEnum.EXPERIENCE,
    }
)


class AuthorityRankingPolicy:
    """Maps a record's status (or the review label) to a tier, and orders tiers."""

    def tier(
        self, status: str | None, *, review_authority: str | None = None, wired: bool = False
    ) -> AuthorityTierEnum:
        """The tier of one record.

        Args:
            status: The stored status; null for an Experience.
            review_authority: The review port's label for the record, when it returned one.
            wired: Whether a review-state port answers; the stored status is then ignored and
                C4's label is mapped, never re-derived.

        Returns:
            The tier; `unreviewed` when the port is wired but has no label for the record.
        """
        if wired:
            if review_authority is None:
                return AuthorityTierEnum.UNREVIEWED
            return _BY_REVIEW_AUTHORITY.get(review_authority, AuthorityTierEnum.UNREVIEWED)
        if status is None:
            return AuthorityTierEnum.EXPERIENCE
        return _BY_STATUS.get(status, AuthorityTierEnum.UNREVIEWED)

    def order_key(self, tier: AuthorityTierEnum) -> int:
        """Sort key of a tier: lower is better; `proposed` and `unreviewed` share a rank."""
        return _TIER_ORDER[tier]
