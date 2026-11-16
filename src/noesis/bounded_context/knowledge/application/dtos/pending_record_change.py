"""A record change a handler wants appended to the change feed."""

from datetime import datetime
from typing import Literal

from noesis.shared_kernel.application.dtos import BaseDto

type ChangeRecordType = Literal[
    "knowledge", "experience", "assertion", "source", "project", "catalog_entry"
]
type ChangeKind = Literal["created", "revised", "status_changed"]


class PendingRecordChange(BaseDto):
    """The facts of one change; the log assigns `event_id` and `sequence`.

    Attributes:
        space_id: Space the record lives in.
        record_id: The record that changed.
        record_type: Kind of the record.
        change_kind: What happened.
        revision: Revision the change refers to; null for types without revisions.
        status: Status after the change; null for types without status.
        occurred_at: When it happened (UTC).
    """

    space_id: str
    record_id: str
    record_type: ChangeRecordType
    change_kind: ChangeKind
    revision: int | None = None
    status: str | None = None
    occurred_at: datetime
