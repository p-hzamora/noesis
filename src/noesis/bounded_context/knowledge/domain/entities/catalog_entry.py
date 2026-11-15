"""The CatalogEntry aggregate: a capability with append-only, gap-free revisions."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Self

from noesis.bounded_context.knowledge.domain.events import (
    CatalogEntryRegistered,
    CatalogEntryRevised,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    CatalogEntryKindEnum,
    CatalogEntryName,
    CatalogRef,
    CatalogRevision,
    RecordId,
    SpaceId,
)
from noesis.exceptions import InvalidCatalogPrerequisiteError, RevisionConflictError
from noesis.shared_kernel.domain.entities import AggregateRoot


def ensure_no_self_prerequisite(
    kind: CatalogEntryKindEnum, name: CatalogEntryName, prerequisites: Sequence[CatalogRef]
) -> None:
    """Fail when an entry lists itself (same kind and name) as a prerequisite.

    Raises:
        InvalidCatalogPrerequisiteError: A prerequisite is the entry itself.
    """
    for prerequisite in prerequisites:
        if prerequisite.kind is kind and prerequisite.name == name:
            raise InvalidCatalogPrerequisiteError(
                f"A catalog entry cannot require itself ({prerequisite.as_text()}).",
                {"ref": prerequisite.as_text()},
                next_steps=["Fix --requires: remove the entry from its own prerequisites."],
            )


@dataclass(slots=True, kw_only=True)
class CatalogEntry(AggregateRoot["CatalogEntry"]):
    """A capability (skill, agent, CLI tool, MCP server). Revisions are append-only.

    It has no status and no availability: whether a capability is installed is a read-time
    fact about a host, never a property of the entry.

    Attributes:
        id: Record id.
        space_id: Owning space, fixed.
        kind: Entry kind, fixed.
        name: Name, unique per space and kind, fixed.
        revisions: Append-only revisions, numbered from 1.
    """

    id: RecordId
    space_id: SpaceId
    kind: CatalogEntryKindEnum
    name: CatalogEntryName
    revisions: tuple[CatalogRevision, ...]

    @property
    def head(self) -> CatalogRevision:
        """The latest revision."""
        return self.revisions[-1]

    @property
    def head_number(self) -> int:
        """Number of the latest revision."""
        return self.head.number

    @property
    def catalog_key(self) -> str:
        """`<space_id>:<kind>:<name>`, the uniqueness key of the entry."""
        return f"{self.space_id.value}:{self.kind.value}:{self.name.value}"

    def head_has_content(
        self,
        *,
        purpose: str,
        version: str | None,
        prerequisites: tuple[CatalogRef, ...],
        location: str,
    ) -> bool:
        """Whether the head already says exactly this, so a revision would change nothing.

        Compares as a revision would store the values (purpose and location trimmed). Creates
        no revision and records no event.
        """
        head: CatalogRevision = self.head
        return (
            purpose.strip() == head.purpose
            and version == head.version
            and prerequisites == head.prerequisites
            and location.strip() == head.location
        )

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
        prerequisites: tuple[CatalogRef, ...] = (),
        location: str,
        actor: Actor,
        source_ids: tuple[RecordId, ...],
        now: datetime,
    ) -> Self:
        """Register an entry with its first revision.

        Raises:
            InvalidCatalogNameError: The name breaks the grammar.
            InvalidCatalogPrerequisiteError: The entry lists itself.
            InvalidRecordError: A blank purpose or location, or no source.

        Returns:
            The entry with `CatalogEntryRegistered` pending.
        """
        entry_name: CatalogEntryName = CatalogEntryName(value=name)
        ensure_no_self_prerequisite(kind, entry_name, prerequisites)
        entry: Self = cls(
            id=id,
            space_id=space_id,
            kind=kind,
            name=entry_name,
            revisions=(
                CatalogRevision(
                    number=1,
                    purpose=purpose,
                    version=version,
                    prerequisites=prerequisites,
                    location=location,
                    actor=actor,
                    source_ids=tuple(dict.fromkeys(source_ids)),
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

    def revise(
        self,
        *,
        expected_revision: int,
        purpose: str,
        version: str | None,
        prerequisites: tuple[CatalogRef, ...],
        location: str,
        actor: Actor,
        source_ids: tuple[RecordId, ...],
        now: datetime,
    ) -> CatalogRevision:
        """Append revision n+1 with the full content given.

        Whether unchanged content deserves a revision is the caller's decision.

        Args:
            expected_revision: The head number the caller based the change on.
            purpose: New purpose.
            version: New declared version, or None for none.
            prerequisites: New prerequisites.
            location: New location.
            actor: Who revises.
            source_ids: Sources of the new revision; at least one.
            now: Revision time.

        Raises:
            RevisionConflictError: `expected_revision` is not the head.
            InvalidCatalogPrerequisiteError: The entry lists itself.
            InvalidRecordError: A blank purpose or location, or no source.

        Returns:
            The new head, with `CatalogEntryRevised` pending.
        """
        if expected_revision != self.head_number:
            raise RevisionConflictError(
                f"Expected revision {expected_revision} but the head is {self.head_number}.",
                {
                    "record_id": self.id.value,
                    "expected_revision": expected_revision,
                    "actual_revision": self.head_number,
                },
                next_steps=["Run `noesis catalog show`, re-apply the change, retry."],
            )
        ensure_no_self_prerequisite(self.kind, self.name, prerequisites)
        revision: CatalogRevision = CatalogRevision(
            number=self.head_number + 1,
            purpose=purpose,
            version=version,
            prerequisites=prerequisites,
            location=location,
            actor=actor,
            source_ids=tuple(dict.fromkeys(source_ids)),
            created_at=now,
        )
        self.revisions = (*self.revisions, revision)
        self.updated_at = now
        self._record(
            CatalogEntryRevised(
                aggregate_id=self.id.value, space_id=self.space_id.value, revision=revision.number
            )
        )
        return revision
