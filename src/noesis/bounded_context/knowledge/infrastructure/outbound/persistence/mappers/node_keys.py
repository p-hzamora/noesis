"""Values of the single-property uniqueness keys (D-013): composite identities as one string."""

import hashlib
import json

from noesis.bounded_context.knowledge.domain.value_objects import (
    ContentHash,
    Key,
    RecordId,
    SourceKindEnum,
    SpaceId,
)


def revision_key(record_id: RecordId, number: int) -> str:
    """`Revision.revision_key`: `<record_id>:<number>`."""
    return f"{record_id.value}:{number}"


def project_key(space_id: SpaceId, key: Key) -> str:
    """`Project.project_key`: `<space_id>:<key>`."""
    return f"{space_id.value}:{key.value}"


def ledger_key(space_id: SpaceId, key: str) -> str:
    """`IdempotencyKey.key`: `<space_id>:<caller key>`, so keys are per space."""
    return f"{space_id.value}:{key}"


def source_key(
    *, space_id: SpaceId, kind: SourceKindEnum, locator: str, digest: ContentHash | None
) -> str:
    """`Source.source_key`: sha256 of the natural key, so a long URL never hits the index limit."""
    natural: str = json.dumps(
        [space_id.value, kind.value, locator, digest.value if digest else None],
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(natural.encode()).hexdigest()}"
