"""The result of a related-record lookup, published by Retrieval for other contexts."""

from typing import Literal

from noesis.utils import FrozenObject


class RecordSearchHitItem(FrozenObject):
    """One hit: a Knowledge or Experience record that matched.

    Attributes:
        record_id: ULID of the record.
        record_type: `knowledge` or `experience`.
        subtype: The record's subtype.
        title: Head-revision title; null for an Experience.
        revision: Head revision; null for an Experience.
        status: Stored status; null for an Experience.
        authority: Authority tier value (`authoritative`, `experience`, `proposed`, ...).
        project_id: The record's project id; null when space-wide.
        sources: Candidate kinds that found the hit, each once (`lexical`, `graph`, `semantic`).
        revised_at: ISO 8601 UTC time of the head revision, ending in `Z`.
        rank: 1-based position in the returned order.
    """

    record_id: str
    record_type: str
    subtype: str | None = None
    title: str | None = None
    revision: int | None = None
    status: str | None = None
    authority: str
    project_id: str | None = None
    sources: tuple[str, ...]
    revised_at: str
    rank: int


class RecordSearchHitContract(FrozenObject):
    """Envelope of a related lookup.

    Attributes:
        contract_version: Schema version of this payload.
        hits: The hits in rank order.
        pending_changes: Largest lag between the change feed head and a projection cursor.
        semantic_state: `absent`, `ready`, `lagging` or `unavailable`.
    """

    contract_version: Literal[1] = 1
    hits: tuple[RecordSearchHitItem, ...]
    pending_changes: int
    semantic_state: str
