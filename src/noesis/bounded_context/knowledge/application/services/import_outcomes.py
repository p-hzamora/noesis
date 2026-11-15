"""The result an import decision produces when it writes nothing (or would write, for an assess)."""

from enum import StrEnum

from noesis.bounded_context.knowledge.application.dtos import ImportKnowledgeResultDto
from noesis.bounded_context.knowledge.application.services.import_request import PreparedImport
from noesis.bounded_context.knowledge.domain.value_objects import (
    ImportCandidate,
    ImportDecision,
    ImportDecisionKindEnum,
    RecordId,
    RecordStatusEnum,
)

UNLINKED_SUCCESSOR_NOTE: str = "assertions unavailable: target not linked"


class ImportOutcomeEnum(StrEnum):
    """What an import of one note ended in."""

    CREATED = "created"
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    REVISED = "revised"
    SUCCESSOR_PROPOSED = "successor_proposed"
    BLOCKED = "blocked"


class ImportBlockReasonEnum(StrEnum):
    """Why an import of one note was blocked."""

    ID_CONFLICT = "id_conflict"
    TARGET_CLOSED = "target_closed"
    REVISION_CONFLICT = "revision_conflict"
    IDEMPOTENCY_KEY_REUSED = "idempotency_key_reused"
    INVALID_METADATA = "invalid_metadata"


def result_of(decision: ImportDecision, prepared: PreparedImport) -> ImportKnowledgeResultDto:
    """The result of `decision`: exact for rows that write nothing, planned for the others."""
    target: ImportCandidate | None = decision.target
    proposed: str = RecordStatusEnum.PROPOSED.value
    if target is None:
        if decision.kind is ImportDecisionKindEnum.ID_CONFLICT:
            return ImportKnowledgeResultDto(
                outcome=ImportOutcomeEnum.BLOCKED, block_reason=ImportBlockReasonEnum.ID_CONFLICT
            )
        declared: RecordId | None = prepared.request.record_id
        return ImportKnowledgeResultDto(
            outcome=ImportOutcomeEnum.CREATED,
            record_id=declared.value if declared is not None else None,
            revision=1,
            status=proposed,
        )
    match decision.kind:
        case ImportDecisionKindEnum.TARGET_CLOSED:
            return ImportKnowledgeResultDto(
                outcome=ImportOutcomeEnum.BLOCKED,
                block_reason=ImportBlockReasonEnum.TARGET_CLOSED,
                record_id=target.id.value,
                status=target.status.value,
            )
        case ImportDecisionKindEnum.UNCHANGED | ImportDecisionKindEnum.CHANGED:
            outcome: ImportOutcomeEnum = (
                ImportOutcomeEnum.UNCHANGED
                if decision.kind is ImportDecisionKindEnum.UNCHANGED
                else ImportOutcomeEnum.CHANGED
            )
            return ImportKnowledgeResultDto(
                outcome=outcome,
                record_id=target.id.value,
                revision=target.head_revision,
                status=target.status.value,
            )
        case ImportDecisionKindEnum.REVISE:
            return ImportKnowledgeResultDto(
                outcome=ImportOutcomeEnum.REVISED,
                record_id=target.id.value,
                revision=target.head_revision + 1,
                status=proposed,
            )
        case ImportDecisionKindEnum.SUCCESSOR_LINKED:
            return ImportKnowledgeResultDto(
                outcome=ImportOutcomeEnum.SUCCESSOR_PROPOSED,
                revision=1,
                status=proposed,
                target_record_id=target.id.value,
            )
        case _:
            return ImportKnowledgeResultDto(
                outcome=ImportOutcomeEnum.CREATED,
                revision=1,
                status=proposed,
                target_record_id=target.id.value,
                reason=UNLINKED_SUCCESSOR_NOTE,
            )
