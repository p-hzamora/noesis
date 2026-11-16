"""One lexical hit of Knowledge's text search."""

from typing import Literal

from noesis.utils import FrozenObject


class RecordHitContract(FrozenObject):
    """A record found by text, best first.

    Attributes:
        contract_version: Schema version of this payload.
        record_id: The record.
        revision: Revision that matched (always the head); null for types without revisions.
        rank: Position in the result, from 1.
    """

    contract_version: Literal[1] = 1
    record_id: str
    revision: int | None = None
    rank: int
