"""The ordered writes a curation will make, fixed before the first one."""

from noesis.bounded_context.knowledge.domain.value_objects.curation_candidate import (
    CurationCandidate,
)
from noesis.bounded_context.knowledge.domain.value_objects.planned_write import PlannedWrite
from noesis.bounded_context.knowledge.domain.value_objects.work_brief import (
    canonical_json,
    sha256_hex,
)
from noesis.shared_kernel.domain.value_objects import ValueObject

FIRST_ORDINAL: int = 1
"""Ordinals start at 1; a skipped candidate keeps its position, so ordinals never shift."""


class PlanEntry(ValueObject):
    """One candidate and what the policy planned for it.

    Attributes:
        ordinal: Its position in the plan, from `FIRST_ORDINAL`.
        candidate: The candidate as read (already redacted).
        write: The planned write.
    """

    ordinal: int
    candidate: CurationCandidate
    write: PlannedWrite


class CurationPlan(ValueObject):
    """The plan of one submission. It is judged once and then saved write-once.

    Attributes:
        entries: One entry per candidate, in the order they were answered.
    """

    entries: tuple[PlanEntry, ...] = ()

    def plan_hash(self) -> str:
        """SHA-256 over the canonical (sorted-key) JSON of the plan.

        The plan holds redacted text only, so a secret never reaches the hash.
        """
        return sha256_hex(canonical_json(self.model_dump(mode="json")))

    def entry(self, ordinal: int) -> PlanEntry | None:
        """The entry with `ordinal`, or None."""
        return next((item for item in self.entries if item.ordinal == ordinal), None)
