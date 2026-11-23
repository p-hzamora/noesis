"""Summary of one assertion, as Retrieval reads it."""

from typing import Literal

from pydantic import Field

from noesis.utils import FrozenObject

ASSERTION_SUMMARY_CONTRACT_VERSION: Literal[1] = 1


class AssertionSummaryContract(FrozenObject):
    """Version 1 of an assertion summary.

    Attributes:
        contract_version: Schema version of this payload.
        assertion_id: ULID of the assertion.
        predicate: `supports`, `contradicts`, `supersedes`, `recommends` or `refines`.
        subject_id: Subject record.
        subject_at_revision: Revision of the subject judged; None for types without revisions.
        object_id: Object record.
        object_at_revision: Revision of the object judged; None for types without revisions.
        object_type: `knowledge`, `assertion` or `catalog_entry`.
        status: Stored status of the assertion.
        evidence_ids: Evidence record ids.
        project_key: The assertion's applicability project key, or None.
        tags: The assertion's applicability tags.
        decision_basis: Why the latest review decision was taken (`user`, `agent_project`, ...);
            None while no decision exists.
    """

    contract_version: Literal[1] = ASSERTION_SUMMARY_CONTRACT_VERSION
    assertion_id: str
    predicate: str
    subject_id: str
    subject_at_revision: int | None = None
    object_id: str
    object_at_revision: int | None = None
    object_type: str
    status: str
    evidence_ids: list[str] = Field(default_factory=list)
    project_key: str | None = None
    tags: list[str] = Field(default_factory=list)
    decision_basis: str | None = None
