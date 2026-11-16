"""What one candidate becomes in the graph: the planned writes of a curation plan."""

from typing import Annotated, Literal

from pydantic import Field

from noesis.shared_kernel.domain.value_objects import ValueObject


class RecordExperience(ValueObject):
    """Record the candidate as an Experience."""

    kind: Literal["record_experience"] = "record_experience"


class ProposeKnowledge(ValueObject):
    """Propose the candidate as new Knowledge, scoped to the brief's project.

    Attributes:
        target_record_id: The record the candidate named, when it is kept but not changed.
        reason: Why the write is not the one the candidate asked for, when it is not.
        evidence_ordinals: Ordinals of the experiences that support it.
    """

    kind: Literal["propose_knowledge"] = "propose_knowledge"
    target_record_id: str | None = None
    reason: str | None = None
    evidence_ordinals: tuple[int, ...] = ()


class ReviseProposal(ValueObject):
    """Revise a `proposed` record at the head the plan was judged against.

    Attributes:
        target_record_id: The record to revise.
        expected_revision: Its head revision when the plan was made.
        evidence_ordinals: Ordinals of the experiences that support it.
    """

    kind: Literal["revise_proposal"] = "revise_proposal"
    target_record_id: str
    expected_revision: int
    evidence_ordinals: tuple[int, ...] = ()


class ProposeSuccessor(ValueObject):
    """Propose new Knowledge, then a proposed `supersedes` assertion from it to the target.

    Attributes:
        target_record_id: The accepted record the new proposal supersedes.
        evidence_ordinals: Ordinals of the experiences that support it.
    """

    kind: Literal["propose_successor"] = "propose_successor"
    target_record_id: str
    evidence_ordinals: tuple[int, ...] = ()


class Skip(ValueObject):
    """Write nothing.

    Attributes:
        reason: Why, as a stable code (`unknown_subtype`, `target_not_found`, ...) or a prefixed
            detail (`curator: ...`, `malformed: ...`).
    """

    kind: Literal["skip"] = "skip"
    reason: str


type PlannedWrite = Annotated[
    RecordExperience | ProposeKnowledge | ReviseProposal | ProposeSuccessor | Skip,
    Field(discriminator="kind"),
]
