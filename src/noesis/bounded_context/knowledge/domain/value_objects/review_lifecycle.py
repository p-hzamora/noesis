"""The review lifecycle: four edges, no way back."""

from typing import ClassVar

from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    RecordStatusEnum,
    ReviewTransitionEnum,
)
from noesis.exceptions import InvalidStatusTransitionError


class ReviewLifecycle:
    """Allowed transitions of Knowledge and Assertion roots."""

    _EDGES: ClassVar[dict[tuple[ReviewTransitionEnum, RecordStatusEnum], RecordStatusEnum]] = {
        (ReviewTransitionEnum.ACCEPT, RecordStatusEnum.PROPOSED): RecordStatusEnum.ACCEPTED,
        (ReviewTransitionEnum.REJECT, RecordStatusEnum.PROPOSED): RecordStatusEnum.RETRACTED,
        (ReviewTransitionEnum.RETRACT, RecordStatusEnum.ACCEPTED): RecordStatusEnum.RETRACTED,
        (ReviewTransitionEnum.SUPERSEDE, RecordStatusEnum.ACCEPTED): RecordStatusEnum.SUPERSEDED,
    }

    @staticmethod
    def next_status(
        transition: ReviewTransitionEnum, current: RecordStatusEnum
    ) -> RecordStatusEnum:
        """Status after `transition` from `current`.

        Raises:
            InvalidStatusTransitionError: The pair is not an edge.
        """
        target: RecordStatusEnum | None = ReviewLifecycle._EDGES.get((transition, current))
        if target is None:
            raise InvalidStatusTransitionError(
                f"Cannot {transition.value} a record that is {current.value}.",
                {"transition": transition.value, "status": current.value},
                next_steps=["Run `noesis record get` to see the current status."],
            )
        return target
