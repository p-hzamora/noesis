"""What an import does with one note: the decision table's row, plus its target."""

from enum import StrEnum

from noesis.bounded_context.knowledge.domain.value_objects.import_candidate import ImportCandidate
from noesis.shared_kernel.domain.value_objects import ValueObject


class ImportDecisionKindEnum(StrEnum):
    """The row of the decision table that fired.

    ID_CONFLICT: the id is held by a record an import must not touch (blocked).
    CREATE: no record matches; create one.
    UNCHANGED: the record already has this content.
    CHANGED: the content differs and the import only reports it.
    REVISE: the target is `proposed`; append a revision.
    SUCCESSOR_LINKED: the target is `accepted`; create a successor and propose `supersedes`.
    SUCCESSOR_UNLINKED: the target is `accepted` and assertions are unavailable; create a successor.
    TARGET_CLOSED: the target is `superseded` or `retracted` (blocked).
    """

    ID_CONFLICT = "id_conflict"
    CREATE = "create"
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    REVISE = "revise"
    SUCCESSOR_LINKED = "successor_linked"
    SUCCESSOR_UNLINKED = "successor_unlinked"
    TARGET_CLOSED = "target_closed"


class ImportDecision(ValueObject):
    """One decision.

    Attributes:
        kind: The decision table row.
        target: The matched record; None for `id_conflict` and `create`.
    """

    kind: ImportDecisionKindEnum
    target: ImportCandidate | None = None
