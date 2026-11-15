"""Values of the single-property uniqueness keys (D-013): composite identities as one string."""

import hashlib
import json

from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    ContentHash,
    Key,
    RecordId,
    SourceKindEnum,
    SpaceId,
    StatementKey,
)


def revision_key(record_id: RecordId, number: int) -> str:
    """`Revision.revision_key`: `<record_id>:<number>`."""
    return f"{record_id.value}:{number}"


def project_key(space_id: SpaceId, key: Key) -> str:
    """`Project.project_key`: `<space_id>:<key>`."""
    return f"{space_id.value}:{key.value}"


def catalog_key(space_id: SpaceId, kind: CatalogEntryKindEnum, name: str) -> str:
    """`CatalogEntry.catalog_key`: `<space_id>:<kind>:<name>`, the name exactly as typed."""
    return f"{space_id.value}:{kind.value}:{name}"


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


def decision_key(record_id: RecordId, seq: int) -> str:
    """`Decision.decision_key`: `<record_id>:<seq>`; one decision per sequence number per record."""
    return f"{record_id.value}:{seq}"


def live_key(statement: StatementKey) -> str:
    """`Assertion.live_key`: sha256 of the canonical statement, set only while it is live."""
    natural: str = json.dumps(
        [
            statement.space_id.value,
            statement.predicate.value,
            statement.subject_id.value,
            statement.object_id.value,
            statement.project_id.value if statement.project_id else None,
        ],
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(natural.encode()).hexdigest()}"
