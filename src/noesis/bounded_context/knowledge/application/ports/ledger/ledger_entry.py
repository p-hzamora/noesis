"""One recorded outcome of a mutating command."""

from datetime import datetime

from pydantic import Field

from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId
from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject


class LedgerEntry(FrozenObject):
    """What a command produced, keyed by (space, idempotency key).

    Attributes:
        space_id: Space the command ran in.
        key: The caller's idempotency key.
        command: Command name; an open set, so later chunks add their own.
        fingerprint: Deterministic hash of the normalised request.
        record_id: The record the command created or changed, when any.
        revision: Revision it produced, when any.
        extra: Further result data a replay needs (a version, a pending-effect flag, ...).
        recorded_at: When the entry was written.
    """

    space_id: SpaceId
    key: str
    command: str
    fingerprint: str
    record_id: RecordId | None = None
    revision: int | None = None
    extra: dict[str, JsonValue] = Field(default_factory=dict)
    recorded_at: datetime
