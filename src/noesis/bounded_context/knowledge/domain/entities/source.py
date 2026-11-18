"""The Source aggregate: where a record's content came from. Write-once."""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from noesis.bounded_context.knowledge.domain.events import SourceRecorded
from noesis.bounded_context.knowledge.domain.value_objects import (
    ContentHash,
    RecordId,
    SourceKindEnum,
    SpaceId,
)
from noesis.exceptions import InvalidRecordError
from noesis.shared_kernel.domain.entities import AggregateRoot


@dataclass(slots=True, kw_only=True)
class Source(AggregateRoot["Source"]):
    """A commit, file version, session, URL or work brief a record cites.

    Locator formats: `commit` = sha (full, or 7+ hex digits from a vault header), `agent_session` = session id, `work_brief` =
    submission key, `file_version` = `vault://<vault_key>/<relative path>`.

    Attributes:
        id: Record id.
        space_id: Owning space, fixed.
        kind: What the source is.
        locator: Where to find it.
        digest: Content hash, when known.
        observed_at: When Knowledge first recorded it (set by Knowledge's clock).
    """

    id: RecordId
    space_id: SpaceId
    kind: SourceKindEnum
    locator: str
    digest: ContentHash | None = None
    observed_at: datetime

    @property
    def natural_key(self) -> tuple[SpaceId, SourceKindEnum, str, ContentHash | None]:
        """What makes a source unique: space, kind, locator and digest."""
        return (self.space_id, self.kind, self.locator, self.digest)

    @classmethod
    def create(
        cls,
        *,
        id: RecordId,
        space_id: SpaceId,
        kind: SourceKindEnum,
        locator: str,
        digest: ContentHash | None = None,
        now: datetime,
    ) -> Self:
        """Record a source, observed `now`.

        Returns:
            The source with `SourceRecorded` pending.
        """
        stripped: str = locator.strip()
        if not stripped:
            raise InvalidRecordError("A source needs a locator.", {"kind": kind.value})
        source: Self = cls(
            id=id,
            space_id=space_id,
            kind=kind,
            locator=stripped,
            digest=digest,
            observed_at=now,
            created_at=now,
            updated_at=now,
        )
        source._record(SourceRecorded(aggregate_id=id.value, space_id=space_id.value, kind=kind))
        return source
