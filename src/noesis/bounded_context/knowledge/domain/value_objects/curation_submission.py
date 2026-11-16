"""What the inbox keeps for one submission: the redacted input to curate."""

from enum import StrEnum

from noesis.bounded_context.knowledge.domain.value_objects.actor import Actor
from noesis.bounded_context.knowledge.domain.value_objects.curation_candidate import (
    CurationCandidate,
)
from noesis.bounded_context.knowledge.domain.value_objects.work_brief import WorkBrief
from noesis.shared_kernel.domain.value_objects import ValueObject


class SubmissionKindEnum(StrEnum):
    """Where the candidates come from: a curator judging a brief, or the caller (apply)."""

    BRIEF = "brief"
    APPLY = "apply"


class CurationSubmission(ValueObject):
    """One submission, redacted, as the inbox keeps it.

    Attributes:
        kind: A brief to judge, or candidates the caller wrote.
        submission_key: Its identity (`WorkBrief.submission_key`, or the apply payload's key).
        project_key: The project every write is scoped to.
        session_id: The agent session recorded as a source of every write.
        commit_shas: The commits recorded as sources of every write.
        actor: Who the writes are made as.
        brief: The brief, for `brief` submissions.
        candidates: The candidates, for `apply` submissions.
    """

    kind: SubmissionKindEnum
    submission_key: str
    project_key: str
    session_id: str
    commit_shas: tuple[str, ...] = ()
    actor: Actor
    brief: WorkBrief | None = None
    candidates: tuple[CurationCandidate, ...] = ()
