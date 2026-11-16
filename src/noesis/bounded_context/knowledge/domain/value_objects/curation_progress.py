"""Where a curation submission stands: `staged -> planned -> applying -> applied`, or failed."""

from enum import StrEnum

from noesis.shared_kernel.domain.value_objects import ValueObject


class CurationStageEnum(StrEnum):
    """A stage of a submission.

    STAGED: kept in the inbox, not judged yet.
    PLANNED: the plan is saved.
    APPLYING: the plan is registered in the ledger; its steps run.
    APPLIED: every step finished (written, replayed or skipped).
    FAILED: a failure; `CurationProgress.failed_at` says where.
    """

    STAGED = "staged"
    PLANNED = "planned"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"


class CurationFailureReasonEnum(StrEnum):
    """Why a submission failed."""

    STORE_UNAVAILABLE = "store_unavailable"
    CURATOR_FAILED = "curator_failed"
    RELATED_LOOKUP_UNAVAILABLE = "related_lookup_unavailable"
    STEP_FAILED = "step_failed"


class CurationProgress(ValueObject):
    """The stage of a submission and, when it failed, where and why.

    Attributes:
        stage: The current stage.
        failed_at: The stage it failed at; set only when `stage` is `failed`.
        reason: Why it failed; set only when `stage` is `failed`.
        error_code: The error code behind a `step_failed`, kept for the retry and the listing.
    """

    stage: CurationStageEnum
    failed_at: CurationStageEnum | None = None
    reason: CurationFailureReasonEnum | None = None
    error_code: str | None = None

    @property
    def is_failed(self) -> bool:
        """Whether the submission is parked."""
        return self.stage is CurationStageEnum.FAILED
