"""The kind matrix and reference rules of a proposed assertion."""

from typing import ClassVar

from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    RecordId,
    RecordReference,
    RecordTypeEnum,
    SpaceId,
)
from noesis.exceptions import InvalidAssertionError

_K, _E, _A = RecordTypeEnum.KNOWLEDGE, RecordTypeEnum.EXPERIENCE, RecordTypeEnum.ASSERTION
_S, _C = RecordTypeEnum.SOURCE, RecordTypeEnum.CATALOG_ENTRY
_P = AssertionPredicateEnum

_MATRIX: dict[AssertionPredicateEnum, dict[RecordTypeEnum, frozenset[RecordTypeEnum]]] = {
    _P.SUPPORTS: {_K: frozenset({_K}), _E: frozenset({_K})},
    _P.CONTRADICTS: {_K: frozenset({_K}), _E: frozenset({_K})},
    _P.SUPERSEDES: {_K: frozenset({_K}), _A: frozenset({_A})},
    _P.RECOMMENDS: {_K: frozenset({_K, _C}), _E: frozenset({_K, _C})},
}


class AssertionStatementPolicy:
    """Checks references, kinds and the project rule; never the status of an endpoint."""

    EVIDENCE_KINDS: ClassVar[frozenset[RecordTypeEnum]] = frozenset({_E, _K, _S})

    @staticmethod
    def check(
        *,
        space_id: SpaceId,
        predicate: AssertionPredicateEnum,
        project_id: RecordId | None,
        subject: RecordReference,
        object: RecordReference,
        evidence: tuple[RecordReference, ...],
    ) -> None:
        """Validate a statement over the referenced records.

        Raises:
            InvalidAssertionError: A reference from another space, a kind outside the matrix,
                an evidence kind that is not Experience, Knowledge or Source, or a `supersedes`
                whose project differs from the object's; the metadata names the field.
        """
        if subject.space_id != space_id:
            raise _invalid("subject", "The subject is not in the active space.")
        if object.space_id != space_id:
            raise _invalid("object", "The object is not in the active space.")
        if any(item.space_id != space_id for item in evidence):
            raise _invalid("evidence", "An evidence record is not in the active space.")
        allowed = _MATRIX[predicate].get(subject.record_type)
        if allowed is None:
            raise _invalid(
                "subject",
                f"A {subject.record_type.value} cannot be the subject of `{predicate.value}`.",
            )
        if object.record_type not in allowed:
            raise _invalid(
                "object",
                f"`{predicate.value}` from a {subject.record_type.value} cannot target "
                f"a {object.record_type.value}.",
            )
        if any(
            item.record_type not in AssertionStatementPolicy.EVIDENCE_KINDS for item in evidence
        ):
            raise _invalid("evidence", "Evidence must be an experience, knowledge or a source.")
        if predicate is _P.SUPERSEDES and project_id != object.project_id:
            raise _invalid(
                "project", "A `supersedes` must have the same project as the record it supersedes."
            )


def _invalid(field: str, message: str) -> InvalidAssertionError:
    return InvalidAssertionError(message, {"field": field}, next_steps=[f"Fix the {field}."])
