"""One record revision with its text: the only way a body reaches Retrieval."""

from datetime import datetime
from typing import Literal

from noesis.utils import FrozenObject


class RecordBodyMissingError(Exception):
    """The requested revision has no body (a file-owned revision), so it cannot be indexed.

    Defined beside the contract because Knowledge's adapter raises it and Knowledge may not
    import Retrieval; Retrieval's port module re-exports it.
    """


class IndexableRecordContract(FrozenObject):
    """A record revision to index.

    Attributes:
        contract_version: Schema version of this payload.
        record_id: The record.
        record_type: Kind of the record.
        subtype: Open subtype; null when the type has none.
        ownership: `graph` or `file`; null for types without ownership.
        revision: The requested revision; null for types without revisions.
        head_revision: The record's current head; null for types without revisions.
        status: Stored status; null for types without status.
        project_id: Project the record is anchored to; null when space-wide.
        tags: Labels, sorted.
        title: Title of the requested revision; null for an Experience.
        body: Text of the requested revision, or of the Experience; never null.
        revised_at: Creation time (UTC) of the requested revision.
    """

    contract_version: Literal[1] = 1
    record_id: str
    record_type: Literal[
        "knowledge", "experience", "assertion", "source", "project", "catalog_entry"
    ]
    subtype: str | None = None
    ownership: str | None = None
    revision: int | None = None
    head_revision: int | None = None
    status: str | None = None
    project_id: str | None = None
    tags: tuple[str, ...] = ()
    title: str | None = None
    body: str
    revised_at: datetime
