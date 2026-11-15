"""Error classes of the review module (20-review.md error table, 25-implementation-map.md)."""

import pytest

from noesis.exceptions import (
    ApplicationException,
    DomainException,
    DuplicateAssertionError,
    EvidenceRequiredError,
    ExpectedRevisionRequiredError,
    InterfaceException,
    InvalidAssertionError,
    InvalidStatusTransitionError,
    RecordNotReviewableError,
    ReferenceNotAcceptableError,
    ReviewNotAuthorisedError,
    StatusConflictError,
    UserPresenceRequiredError,
)
from noesis.exceptions.exit_code_enum import ExitCodeEnum

pytestmark = pytest.mark.unit

CASES: list[tuple[type[Exception], str, type[Exception]]] = [
    (InvalidAssertionError, "KNOWLEDGE_020_INVALID_ASSERTION", DomainException),
    (InvalidStatusTransitionError, "KNOWLEDGE_021_INVALID_STATUS_TRANSITION", DomainException),
    (ReviewNotAuthorisedError, "KNOWLEDGE_022_REVIEW_NOT_AUTHORISED", DomainException),
    (EvidenceRequiredError, "KNOWLEDGE_023_EVIDENCE_REQUIRED", DomainException),
    (StatusConflictError, "KNOWLEDGE_220_STATUS_CONFLICT", ApplicationException),
    (DuplicateAssertionError, "KNOWLEDGE_221_DUPLICATE_ASSERTION", ApplicationException),
    (ReferenceNotAcceptableError, "KNOWLEDGE_222_REFERENCE_NOT_ACCEPTABLE", ApplicationException),
    (
        ExpectedRevisionRequiredError,
        "KNOWLEDGE_223_EXPECTED_REVISION_REQUIRED",
        ApplicationException,
    ),
    (RecordNotReviewableError, "KNOWLEDGE_224_RECORD_NOT_REVIEWABLE", ApplicationException),
]


@pytest.mark.parametrize(("error_class", "code", "base"), CASES)
def test_review_error_has_stable_code_failure_exit_code_and_layer(
    error_class: type[Exception], code: str, base: type[Exception]
) -> None:
    error = error_class("boom", {"field": "object"}, next_steps=["fix it"])  # type: ignore[call-arg]

    assert error.error_code == code  # type: ignore[attr-defined]
    assert int(error.exit_code) == 1  # type: ignore[attr-defined]
    assert isinstance(error, base)
    assert error.metadata == {"field": "object"}  # type: ignore[attr-defined]
    assert error.next_steps == ("fix it",)  # type: ignore[attr-defined]


def test_user_presence_error_is_an_interface_error_that_exits_one_not_two() -> None:
    """`InterfaceException` defaults to the usage exit code 2; this one overrides it."""
    error = UserPresenceRequiredError("needs a terminal")

    assert error.error_code == "INTERFACE_006_USER_PRESENCE_REQUIRED"
    assert isinstance(error, InterfaceException)
    assert error.exit_code is ExitCodeEnum.FAILURE
    assert int(error.exit_code) == 1
