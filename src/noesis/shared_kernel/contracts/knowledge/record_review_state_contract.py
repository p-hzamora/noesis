"""Review state of one record, as Retrieval reads it."""

from typing import Literal

from pydantic import Field

from noesis.utils import FrozenObject

RECORD_REVIEW_STATE_CONTRACT_VERSION: Literal[1] = 1


class RecordReviewStateContract(FrozenObject):
    """Version 1 of a record's review state.

    Attributes:
        contract_version: Schema version of this payload.
        record_id: ULID of the record.
        record_type: `knowledge`, `experience`, `assertion`, `source`, `project` or `catalog_entry`.
        status: Stored status; None for types without status.
        effective_status: Derived status; None for types without status.
        authority: `authoritative`, `proposed`, `superseded`, `retracted` or `not_reviewable`.
        head_revision: Head revision for types with revisions, else None.
        superseded_by_assertion_id: The accepted `supersedes` assertion targeting the record.
        superseded_by_record_ids: Subjects of the accepted `supersedes` assertions targeting it.
        project_key: Applicability project key; None when space-wide or not applicable.
        tags: Applicability tags.
        decided_by_kind: `user` or `agent` of the latest decision, or None.
        decided_at: ISO 8601 time of the latest decision, or None.
    """

    contract_version: Literal[1] = RECORD_REVIEW_STATE_CONTRACT_VERSION
    record_id: str
    record_type: str
    status: str | None = None
    effective_status: str | None = None
    authority: str
    head_revision: int | None = None
    superseded_by_assertion_id: str | None = None
    superseded_by_record_ids: list[str] = Field(default_factory=list)
    project_key: str | None = None
    tags: list[str] = Field(default_factory=list)
    decided_by_kind: str | None = None
    decided_at: str | None = None
