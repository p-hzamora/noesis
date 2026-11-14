"""Error classes of the Knowledge context (spec 40-cli-and-errors)."""

import pytest

from noesis.exceptions import (
    ApplicationException,
    DomainException,
    EntryAlreadyExistsError,
    ExperienceWithoutSourceError,
    IdempotencyKeyReusedError,
    InvalidContentHashError,
    InvalidKeyError,
    InvalidRecordError,
    InvalidRecordIdError,
    InvalidSlugError,
    KnowledgeNotRevisableError,
    RecordNotFoundError,
    RecordNotRevisableError,
    ReferenceNotInSpaceError,
    RevisionConflictError,
    SpaceNotFoundError,
    StoreNotInitialisedError,
)
from noesis.exceptions.exit_code_enum import ExitCodeEnum

pytestmark = pytest.mark.unit

CASES: list[tuple[type[Exception], str, type[Exception]]] = [
    (InvalidRecordIdError, "KNOWLEDGE_001_INVALID_RECORD_ID", DomainException),
    (InvalidSlugError, "KNOWLEDGE_002_INVALID_SLUG", DomainException),
    (InvalidContentHashError, "KNOWLEDGE_003_INVALID_CONTENT_HASH", DomainException),
    (InvalidKeyError, "KNOWLEDGE_004_INVALID_KEY", DomainException),
    (KnowledgeNotRevisableError, "KNOWLEDGE_005_KNOWLEDGE_NOT_REVISABLE", DomainException),
    (ExperienceWithoutSourceError, "KNOWLEDGE_006_EXPERIENCE_WITHOUT_SOURCE", DomainException),
    (InvalidRecordError, "KNOWLEDGE_007_INVALID_RECORD", DomainException),
    (RecordNotFoundError, "KNOWLEDGE_201_RECORD_NOT_FOUND", ApplicationException),
    (RevisionConflictError, "KNOWLEDGE_202_REVISION_CONFLICT", ApplicationException),
    (IdempotencyKeyReusedError, "KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED", ApplicationException),
    (StoreNotInitialisedError, "KNOWLEDGE_204_STORE_NOT_INITIALISED", ApplicationException),
    (ReferenceNotInSpaceError, "KNOWLEDGE_205_REFERENCE_NOT_IN_SPACE", ApplicationException),
    (EntryAlreadyExistsError, "KNOWLEDGE_206_ENTRY_ALREADY_EXISTS", ApplicationException),
    (RecordNotRevisableError, "KNOWLEDGE_207_RECORD_NOT_REVISABLE", ApplicationException),
    (SpaceNotFoundError, "KNOWLEDGE_208_SPACE_NOT_FOUND", ApplicationException),
]


@pytest.mark.parametrize(("error_class", "code", "base"), CASES)
def test_error_has_stable_code_failure_exit_code_and_layer(
    error_class: type[Exception], code: str, base: type[Exception]
) -> None:
    error = error_class("boom", {"k": "v"}, next_steps=["do this"])  # type: ignore[call-arg]

    assert error.error_code == code  # type: ignore[attr-defined]
    assert error.exit_code is ExitCodeEnum.FAILURE  # type: ignore[attr-defined]
    assert int(error.exit_code) == 1  # type: ignore[attr-defined]
    assert isinstance(error, base)
    assert error.metadata == {"k": "v"}  # type: ignore[attr-defined]
    assert error.next_steps == ("do this",)  # type: ignore[attr-defined]


def test_error_codes_are_unique() -> None:
    codes = [code for _, code, _ in CASES]
    assert len(codes) == len(set(codes))
