"""The `:Embedding` chunk node and the vector index Retrieval owns (Q-202, F-3).

`:Embedding {embedding_key, space_id, record_id, revision?, revision_key, profile_hash,
chunk_index, chunk_count, token_start, token_end, content_hash, vector}`. One node per chunk;
Knowledge's Revision nodes are never touched. `revision` is absent for an Experience (decoded
to null) and `revision_key` is `none` for it: no fictitious revision 0.
"""

import hashlib
import json
from typing import Final

from noesis.shared_kernel.contracts.knowledge import IndexableRecordContract

SEMANTIC_KIND: Final[str] = "semantic"
EMBEDDING_LABEL: Final[str] = "Embedding"
VECTOR_INDEX_NAME: Final[str] = "retrieval_semantic_vector"
NO_REVISION_KEY: Final[str] = "none"


def revision_key(revision: int | None) -> str:
    """The identity part of a revision: its number, or `none` for an unrevisioned record."""
    return NO_REVISION_KEY if revision is None else str(revision)


def embedding_key(
    space_id: str, record_id: str, revision: int | None, profile_hash: str, chunk_index: int
) -> str:
    """Canonical JSON encoding of the identity tuple; no delimiter can collide."""
    return json.dumps(
        [space_id, record_id, revision_key(revision), profile_hash, chunk_index],
        separators=(",", ":"),
    )


def passage_text(record: IndexableRecordContract) -> str:
    """The text embedded for a record: a nonempty title, a newline and the body, or the body."""
    title: str = (record.title or "").strip()
    return f"{title}\n{record.body}" if title else record.body


def content_hash(text: str) -> str:
    """Digest of the embedded text, to skip re-embedding unchanged records."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
