"""The result of a similar-records lookup, published by Retrieval for other contexts."""

from typing import Literal

from noesis.utils import FrozenObject


class SimilarRecordHitItem(FrozenObject):
    """One record found near an anchor.

    Attributes:
        record_id: ULID of the record.
        revision: Head revision the source found; null when unknown.
        rank: 1-based position in the returned order.
        found_by: Candidate kinds that found it, each once (`lexical`, `graph`, `semantic`).
    """

    record_id: str
    revision: int | None = None
    rank: int
    found_by: tuple[str, ...]


class SimilarRecordsContract(FrozenObject):
    """Envelope of a similar-records lookup; ranks order hits, they are not similarity scores.

    Attributes:
        contract_version: Schema version of this payload.
        anchor_id: The record the hits are near.
        hits: The hits in rank order; the anchor is never one of them.
        semantic_state: `absent`, `ready`, `lagging` or `unavailable`.
        similarity: Always null: no score is fabricated.
    """

    contract_version: Literal[1] = 1
    anchor_id: str
    hits: tuple[SimilarRecordHitItem, ...]
    semantic_state: str
    similarity: None = None
