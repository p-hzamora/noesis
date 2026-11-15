"""ReviewLifecycle: every (transition, from-status) pair (FR-004; lifecycle table)."""

import pytest

from noesis.bounded_context.knowledge.domain.value_objects import RecordStatusEnum
from noesis.bounded_context.knowledge.domain.value_objects.enums import ReviewTransitionEnum
from noesis.bounded_context.knowledge.domain.value_objects.review_lifecycle import ReviewLifecycle
from noesis.exceptions import InvalidStatusTransitionError

pytestmark = pytest.mark.unit

PROPOSED, ACCEPTED = RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED
SUPERSEDED, RETRACTED = RecordStatusEnum.SUPERSEDED, RecordStatusEnum.RETRACTED

# no back edges: these four are the only edges
ALLOWED: dict[tuple[ReviewTransitionEnum, RecordStatusEnum], RecordStatusEnum] = {
    (ReviewTransitionEnum.ACCEPT, PROPOSED): ACCEPTED,
    (ReviewTransitionEnum.REJECT, PROPOSED): RETRACTED,
    (ReviewTransitionEnum.RETRACT, ACCEPTED): RETRACTED,
    (ReviewTransitionEnum.SUPERSEDE, ACCEPTED): SUPERSEDED,
}


@pytest.mark.parametrize("transition", ReviewTransitionEnum)
@pytest.mark.parametrize("current", RecordStatusEnum)
def test_next_status_follows_the_table_and_refuses_every_other_pair(
    transition: ReviewTransitionEnum, current: RecordStatusEnum
) -> None:
    if (transition, current) in ALLOWED:
        assert ReviewLifecycle.next_status(transition, current) is ALLOWED[(transition, current)]
        return
    with pytest.raises(InvalidStatusTransitionError) as raised:
        ReviewLifecycle.next_status(transition, current)
    assert raised.value.error_code == "KNOWLEDGE_021_INVALID_STATUS_TRANSITION"
