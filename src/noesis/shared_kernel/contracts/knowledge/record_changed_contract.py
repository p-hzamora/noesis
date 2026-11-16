"""One entry of Knowledge's change feed, as Retrieval reads it (`changes_after`)."""

from datetime import datetime
from typing import Literal

from noesis.utils import FrozenObject


class RecordChangedContract(FrozenObject):
    """A record was created, revised or changed status.

    Attributes:
        contract_version: Schema version of this payload.
        event_id: Unique id of this change (uuid4 hex).
        occurred_at: When it happened (UTC, Knowledge's clock).
        sequence: Position in the space's feed: consecutive and gap-free from 1.
        space_id: Space the record lives in.
        record_id: The record that changed.
        record_type: Kind of the record.
        change_kind: What happened; the closed set, with no link-set kind (wiki links are not data).
        revision: Revision the change refers to; null for types without revisions.
        status: Status after the change; null for types without status.
    """

    contract_version: Literal[1] = 1
    event_id: str
    occurred_at: datetime
    sequence: int
    space_id: str
    record_id: str
    record_type: Literal[
        "knowledge", "experience", "assertion", "source", "project", "catalog_entry"
    ]
    change_kind: Literal["created", "revised", "status_changed"]
    revision: int | None = None
    status: str | None = None
