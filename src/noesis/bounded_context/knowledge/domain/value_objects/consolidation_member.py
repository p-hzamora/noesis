"""What a consolidation records about each original, and what a dismissal records about why."""

from datetime import datetime

from noesis.bounded_context.knowledge.domain.value_objects.actor import Actor
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    DismissalReasonKindEnum,
    RecordStatusEnum,
)
from noesis.bounded_context.knowledge.domain.value_objects.record_id import RecordId
from noesis.bounded_context.knowledge.domain.value_objects.slug import Slug
from noesis.shared_kernel.domain.value_objects import ValueObject


class ConsolidationMember(ValueObject):
    """One original, pinned at the immutable accepted head revision that was judged.

    Attributes:
        record_id: The Knowledge record.
        at_revision: Its head revision when the consolidation was opened.
    """

    record_id: RecordId
    at_revision: int


class MemberCandidate(ValueObject):
    """A record as the eligibility policy sees it; the application builds it from the store.

    Attributes:
        record_id: The record.
        found: Whether it exists in the command's space.
        is_knowledge: Whether it is a Knowledge record (not an Experience, Assertion, ...).
        effective_status: Derived status; None for types without status.
        subtype: Knowledge subtype.
        project_id: Applicability project; None when space-wide.
        head_revision: Head revision.
        tags: Applicability tags as strings.
    """

    record_id: RecordId
    found: bool = True
    is_knowledge: bool = True
    effective_status: RecordStatusEnum | None = None
    subtype: Slug | None = None
    project_id: RecordId | None = None
    head_revision: int | None = None
    tags: tuple[str, ...] = ()


class ConsolidationDismissal(ValueObject):
    """Why and by whom a consolidation was dismissed.

    Attributes:
        reason_kind: `distinct`, `poor_draft` or `other`.
        reason: Redacted explanation.
        actor: Who dismissed it.
        dismissed_at: When.
    """

    reason_kind: DismissalReasonKindEnum
    reason: str
    actor: Actor
    dismissed_at: datetime


class DismissedPair(ValueObject):
    """Two originals a `distinct` dismissal judged, at the revisions judged.

    Attributes:
        consolidation_id: The dismissed consolidation.
        first_id: The smaller record id.
        first_revision: Its judged revision.
        second_id: The larger record id.
        second_revision: Its judged revision.
    """

    consolidation_id: str
    first_id: str
    first_revision: int
    second_id: str
    second_revision: int
