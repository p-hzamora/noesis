"""The current state of one record, as Retrieval reads it (`get_states`, `scan_states`)."""

from datetime import datetime
from typing import Literal

from noesis.utils import FrozenObject


class RecordStateContract(FrozenObject):
    """What Retrieval needs to resolve, filter and rank a record.

    Attributes:
        contract_version: Schema version of this payload.
        record_id: The record.
        record_type: Kind of the record.
        subtype: Open subtype; null when the type has none.
        ownership: `graph` or `file`; null for types without ownership.
        head_revision: Head revision number; null for types without revisions.
        status: Stored status; null for types without status.
        project_id: Project the record is anchored to; null when space-wide.
        tags: Labels, sorted.
        title: Head revision title; null for an Experience.
        revised_at: Creation time (UTC) of the head revision, or of the record when the type has
            no revisions.
    """

    contract_version: Literal[1] = 1
    record_id: str
    record_type: Literal[
        "knowledge", "experience", "assertion", "source", "project", "catalog_entry"
    ]
    subtype: str | None = None
    ownership: str | None = None
    head_revision: int | None = None
    status: str | None = None
    project_id: str | None = None
    tags: tuple[str, ...] = ()
    title: str | None = None
    revised_at: datetime
