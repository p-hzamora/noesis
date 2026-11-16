"""What the inbox keeps per ticket: the submission, its progress, the plan and the step outcomes."""

from datetime import datetime
from enum import StrEnum

from noesis.bounded_context.knowledge.application.dtos import RelatedLookupDto
from noesis.bounded_context.knowledge.domain.value_objects import (
    CurationPlan,
    CurationProgress,
    CurationSubmission,
)
from noesis.utils import FrozenObject


class StepOutcomeEnum(StrEnum):
    """How a step ended: written now, replayed from the ledger, or skipped."""

    WRITTEN = "written"
    REPLAYED = "replayed"
    SKIPPED = "skipped"


class StepOutcome(FrozenObject):
    """The outcome of one step, kept beside the plan (the plan itself is write-once).

    Attributes:
        ordinal: The candidate's ordinal.
        step: The step name (`experience`, `knowledge`, `revise`, `supersedes`, `supports-<n>`).
        outcome: How it ended.
        reason: Why it was skipped (`target_changed`), when it was.
    """

    ordinal: int
    step: str
    outcome: StepOutcomeEnum
    reason: str | None = None


class CurationTicket(FrozenObject):
    """One submission in the inbox.

    Attributes:
        ticket: Its id, derived from the submission key.
        submission: The redacted submission.
        progress: Where it stands.
        plan: The write-once plan, once saved.
        related_lookup: How the related lookup went when the plan was judged; None until then.
        steps: The step outcomes recorded so far, the latest per step.
        created_at: When it was staged.
        updated_at: When it last changed.
        parked_at: When it last failed; None unless it is failed.
    """

    ticket: str
    submission: CurationSubmission
    progress: CurationProgress
    plan: CurationPlan | None = None
    related_lookup: RelatedLookupDto | None = None
    steps: tuple[StepOutcome, ...] = ()
    created_at: datetime
    updated_at: datetime
    parked_at: datetime | None = None

    def step(self, ordinal: int, step: str) -> StepOutcome | None:
        """The recorded outcome of a step, or None."""
        return next(
            (item for item in self.steps if item.ordinal == ordinal and item.step == step), None
        )
