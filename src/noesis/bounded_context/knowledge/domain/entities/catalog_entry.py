"""The CatalogEntry aggregate (type only in C2; storage comes with C6)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from noesis.bounded_context.knowledge.domain.events import CatalogEntryRegistered
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    CatalogRevision,
    RecordId,
    SpaceId,
)
from noesis.exceptions import InvalidRecordError
from noesis.shared_kernel.domain.entities import AggregateRoot


@dataclass(slots=True, kw_only=True)
class CatalogEntry(AggregateRoot["CatalogEntry"]):
    """A capability (skill, agent, CLI tool, MCP server). Revisions are append-only.

    It has no status: availability is never a property of the entry.

    Attributes:
        id: Record id.
        space_id: Owning space, fixed.
        kind: Entry kind.
        name: Name, unique per space and kind.
        revisions: Append-only revisions, numbered from 1.
    """

    id: RecordId
    space_id: SpaceId
    kind: CatalogEntryKindEnum
    name: str
    revisions: tuple[CatalogRevision, ...]

    @classmethod
    def create(
        cls,
        *,
        id: RecordId,
        space_id: SpaceId,
        kind: CatalogEntryKindEnum,
        name: str,
        purpose: str,
        version: str | None = None,
        prerequisites: tuple[str, ...] = (),
        location: str | None = None,
        now: datetime,
    ) -> Self:
        """Register an entry with its first revision.

        Returns:
            The entry with `CatalogEntryRegistered` pending.
        """
        if not name.strip() or not purpose.strip():
            raise InvalidRecordError("A catalog entry needs a name and a purpose.")
        entry: Self = cls(
            id=id,
            space_id=space_id,
            kind=kind,
            name=name.strip(),
            revisions=(
                CatalogRevision(
                    number=1,
                    purpose=purpose.strip(),
                    version=version,
                    prerequisites=prerequisites,
                    location=location,
                    created_at=now,
                ),
            ),
            created_at=now,
            updated_at=now,
        )
        entry._record(
            CatalogEntryRegistered(aggregate_id=id.value, space_id=space_id.value, kind=kind)
        )
        return entry
