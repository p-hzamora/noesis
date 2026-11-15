"""Idempotency keys and content hash of the vault import (`20-import.md`, "Idempotency")."""

import hashlib
import json

from noesis.bounded_context.knowledge.domain.value_objects import (
    ContentHash,
    GraphContent,
    RecordId,
)

IMPORT_CREATE_COMMAND: str = "import_knowledge.create"
IMPORT_REVISE_COMMAND: str = "import_knowledge.revise"
IMPORT_SUCCESSOR_COMMAND: str = "import_knowledge.successor"

FINGERPRINT_EXCLUDE: set[str] = {"idempotency_key", "actor", "on_change", "contract_version"}
"""Request fields left out of the fingerprint: who ran it and how it was asked do not change it."""


def content_hash(content: GraphContent, digest: ContentHash) -> str:
    """`sha256:` of the canonical JSON of the stored title, stored body and file digest."""
    canonical: str = json.dumps(
        {"body": content.body, "digest": digest.value, "title": content.title},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def create_key(record_id: RecordId | None, locator: str, hashed: str) -> str:
    """Key of a create; without a declared id it is derived from the redacted locator."""
    subject: str = (
        record_id.value
        if record_id is not None
        else f"loc-{hashlib.sha256(locator.encode()).hexdigest()}"
    )
    return f"import/v1/create/{subject}/0/{hashed}"


def revise_key(target_id: RecordId, head: int, hashed: str) -> str:
    """Key of a revise of `target_id` whose head is `head`."""
    return f"import/v1/revise/{target_id.value}/{head}/{hashed}"


def successor_key(target_id: RecordId, head: int, hashed: str) -> str:
    """Key of a successor of the accepted `target_id` whose head is `head`."""
    return f"import/v1/successor/{target_id.value}/{head}/{hashed}"


def supersedes_key(successor_id: RecordId, target_id: RecordId) -> str:
    """Key of the `supersedes` proposal from a successor to its target."""
    return f"import/v1/supersedes/{successor_id.value}/{target_id.value}"
