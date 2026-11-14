"""Request fingerprints and ledger replay rules."""

import hashlib
import json

from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.domain.value_objects import SpaceId
from noesis.exceptions import IdempotencyKeyReusedError
from noesis.utils import FrozenObject


def fingerprint_request(
    command_name: str, request: FrozenObject, *, exclude: set[str] | None = None
) -> str:
    """Deterministic hash of a command name and its normalised request.

    Args:
        command_name: The ledger command name.
        request: The command; fields are dumped as JSON with sorted keys.
        exclude: Field names left out (the idempotency key itself).

    Returns:
        `sha256:<hex>`.
    """
    payload: object = request.model_dump(mode="json", exclude=exclude or set())
    canonical: str = json.dumps(
        {"command": command_name, "request": payload}, sort_keys=True, separators=(",", ":")
    )
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def replay_of(entry: LedgerEntry | None, *, command: str, fingerprint: str) -> LedgerEntry | None:
    """The entry to replay, or None when the key is unused.

    Raises:
        IdempotencyKeyReusedError: The key was used for a different command or request.
    """
    if entry is None:
        return None
    if entry.command != command or entry.fingerprint != fingerprint:
        raise IdempotencyKeyReusedError(
            f"Idempotency key {entry.key!r} was already used for a different request.",
            {"key": entry.key, "command": entry.command},
            next_steps=["Use a new idempotency key for a different request."],
        )
    return entry


async def read_ledger(
    uow_factory: KnowledgeUnitOfWorkFactory, space_id: SpaceId, key: str
) -> LedgerEntry | None:
    """Read one ledger entry in its own read-only unit of work."""
    async with uow_factory() as uow:
        return await uow.ledger.get(space_id, key)
