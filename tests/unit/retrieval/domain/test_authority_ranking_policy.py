"""Authority tiers and their order (AC-023, authority step table)."""

import pytest

from noesis.bounded_context.retrieval.domain.enums import AuthorityTierEnum
from noesis.bounded_context.retrieval.domain.policies.authority_ranking_policy import (
    AuthorityRankingPolicy,
)

pytestmark = pytest.mark.unit

POLICY = AuthorityRankingPolicy()


@pytest.mark.parametrize(
    ("status", "tier"),
    [
        ("accepted", "authoritative"),
        ("proposed", "proposed"),
        ("superseded", "superseded"),
        ("retracted", "retracted"),
        (None, "experience"),
    ],
)
def test_unwired_tier_follows_the_stored_status(status: str | None, tier: str) -> None:
    assert POLICY.tier(status) == AuthorityTierEnum(tier)
    assert POLICY.tier(status, wired=False) == AuthorityTierEnum(tier)


@pytest.mark.parametrize(
    ("authority", "tier"),
    [
        ("authoritative", "authoritative"),
        ("proposed", "proposed"),
        ("superseded", "superseded"),
        ("retracted", "retracted"),
        ("not_reviewable", "experience"),
        (None, "unreviewed"),
    ],
)
def test_wired_tier_maps_the_review_authority(authority: str | None, tier: str) -> None:
    """The stored status is ignored once the review-state port answers (C4's label is not re-derived)."""
    assert POLICY.tier("accepted", review_authority=authority, wired=True) == AuthorityTierEnum(
        tier
    )


def test_tier_order_is_authoritative_experience_proposed_superseded_retracted() -> None:
    ordered = sorted(
        AuthorityTierEnum,
        key=POLICY.order_key,
    )

    assert [tier.value for tier in ordered[:1]] == ["authoritative"]
    assert ordered[1] is AuthorityTierEnum.EXPERIENCE
    assert {ordered[2], ordered[3]} == {AuthorityTierEnum.PROPOSED, AuthorityTierEnum.UNREVIEWED}
    assert ordered[4] is AuthorityTierEnum.SUPERSEDED
    assert ordered[5] is AuthorityTierEnum.RETRACTED


def test_proposed_and_unreviewed_share_a_rank() -> None:
    assert POLICY.order_key(AuthorityTierEnum.PROPOSED) == POLICY.order_key(
        AuthorityTierEnum.UNREVIEWED
    )


def test_tier_values_are_the_documented_strings() -> None:
    assert {tier.value for tier in AuthorityTierEnum} == {
        "authoritative",
        "experience",
        "proposed",
        "unreviewed",
        "superseded",
        "retracted",
    }
