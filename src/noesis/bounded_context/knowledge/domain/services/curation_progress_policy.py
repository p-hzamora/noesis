"""The transitions of a curation submission's progress."""

from noesis.bounded_context.knowledge.domain.value_objects.curation_progress import (
    CurationFailureReasonEnum,
    CurationProgress,
    CurationStageEnum,
)
from noesis.exceptions import InvalidCurationTransitionError

_FORWARD: dict[CurationStageEnum, CurationStageEnum] = {
    CurationStageEnum.STAGED: CurationStageEnum.PLANNED,
    CurationStageEnum.PLANNED: CurationStageEnum.APPLYING,
    CurationStageEnum.APPLYING: CurationStageEnum.APPLIED,
}


class CurationProgressPolicy:
    """`staged -> planned -> applying -> applied`; `failed` from any stage but `applied`.

    A failed submission returns to the stage it failed at (a retry, or the same submission
    ingested again). Any other transition is rejected.
    """

    @staticmethod
    def initial() -> CurationProgress:
        """The progress of a submission just staged."""
        return CurationProgress(stage=CurationStageEnum.STAGED)

    @staticmethod
    def advance(progress: CurationProgress, to: CurationStageEnum) -> CurationProgress:
        """Move forward one stage, or from `failed` back to its `failed_at` stage.

        Raises:
            InvalidCurationTransitionError: The table has no such transition.
        """
        if progress.is_failed:
            if to is progress.failed_at:
                return CurationProgress(stage=to)
        elif _FORWARD.get(progress.stage) is to:
            return CurationProgress(stage=to)
        raise InvalidCurationTransitionError(
            f"A curation cannot go from {progress.stage.value} to {to.value}.",
            {"from": progress.stage.value, "to": to.value},
        )

    @staticmethod
    def fail(
        progress: CurationProgress,
        reason: CurationFailureReasonEnum,
        *,
        error_code: str | None = None,
    ) -> CurationProgress:
        """Record a failure at the current stage.

        Raises:
            InvalidCurationTransitionError: The submission is applied or already failed.
        """
        if progress.is_failed or progress.stage is CurationStageEnum.APPLIED:
            raise InvalidCurationTransitionError(
                f"A curation that is {progress.stage.value} cannot fail.",
                {"from": progress.stage.value, "to": CurationStageEnum.FAILED.value},
            )
        return CurationProgress(
            stage=CurationStageEnum.FAILED,
            failed_at=progress.stage,
            reason=reason,
            error_code=error_code,
        )

    @staticmethod
    def resume(progress: CurationProgress) -> CurationProgress:
        """A failed submission back at its `failed_at` stage; any other progress unchanged."""
        if progress.failed_at is None or not progress.is_failed:
            return progress
        return CurationProgressPolicy.advance(progress, progress.failed_at)
