"""Facet coverage status per 10-cli.md."""

import pytest

from noesis.bounded_context.retrieval.domain.enums import (
    AuthorityTierEnum,
    CoverageStatusEnum,
    SupportKindEnum,
)
from noesis.bounded_context.retrieval.domain.policies.coverage_status_policy import (
    CoverageStatusPolicy,
)
from noesis.bounded_context.retrieval.domain.value_objects.facet_support import FacetSupport

pytestmark = pytest.mark.unit
policy = CoverageStatusPolicy()
RES, REC = SupportKindEnum.RESOURCE, SupportKindEnum.RECORD
C = CoverageStatusEnum


def resource(available: bool | None) -> FacetSupport:
    return FacetSupport(kind=RES, available=available)


def record(tier: AuthorityTierEnum) -> FacetSupport:
    return FacetSupport(kind=REC, authority=tier)


@pytest.mark.parametrize(
    ("support", "unreadable", "expected"),
    [
        ([], False, C.MISSING),
        ([], True, C.UNKNOWN),
        ([resource(True)], False, C.COVERED),
        ([resource(None)], False, C.COVERED),
        ([record(AuthorityTierEnum.AUTHORITATIVE)], False, C.COVERED),
        ([resource(False)], False, C.PARTIAL),
        ([record(AuthorityTierEnum.PROPOSED)], False, C.PARTIAL),
        ([record(AuthorityTierEnum.UNREVIEWED)], False, C.MISSING),
        ([resource(False), record(AuthorityTierEnum.AUTHORITATIVE)], False, C.COVERED),
        ([resource(False)], True, C.PARTIAL),
    ],
)
def test_status(
    support: list[FacetSupport], unreadable: bool, expected: CoverageStatusEnum
) -> None:
    assert policy.status(support, unreadable=unreadable) is expected
