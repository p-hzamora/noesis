"""What Knowledge answers about one imported note or file (JSON-native, versioned)."""

from typing import Literal

from noesis.utils import FrozenObject

IMPORT_KNOWLEDGE_OUTCOME_VERSION: Literal[1] = 1


class ImportKnowledgeOutcomeContract(FrozenObject):
    """Version 1 of the answer to an import request (planned for an assess, done for an apply).

    Attributes:
        contract_version: Schema version of this payload.
        outcome: `created`, `unchanged`, `changed`, `revised`, `successor_proposed` or `blocked`.
        record_id: The record created, revised or matched; None for a planned create without a
            given id and for a block before a target is known.
        revision: Revision written or planned; the head for `unchanged` and `changed`; None for
            `blocked`.
        status: Status of `record_id`.
        target_record_id: The accepted record a successor replaces; else None.
        assertion_id: The proposed `supersedes` assertion (apply only); else None.
        block_reason: `id_conflict`, `target_closed`, `revision_conflict`,
            `idempotency_key_reused` or `invalid_metadata`; None unless `blocked`.
        reason: The reduced-behaviour note of a successor without assertions; else None.
        detail: The error code behind `invalid_metadata`; else None.
        replayed: True when the result came from the idempotency ledger.
    """

    contract_version: Literal[1] = IMPORT_KNOWLEDGE_OUTCOME_VERSION
    outcome: str
    record_id: str | None = None
    revision: int | None = None
    status: str | None = None
    target_record_id: str | None = None
    assertion_id: str | None = None
    block_reason: str | None = None
    reason: str | None = None
    detail: str | None = None
    replayed: bool = False
