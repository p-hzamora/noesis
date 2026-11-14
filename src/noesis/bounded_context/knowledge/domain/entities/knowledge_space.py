"""The KnowledgeSpace aggregate: the container every record belongs to."""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from noesis.bounded_context.knowledge.domain.events import KnowledgeSpaceCreated
from noesis.bounded_context.knowledge.domain.value_objects import Key, SpaceId
from noesis.exceptions import InvalidRecordError
from noesis.shared_kernel.domain.entities import AggregateRoot


@dataclass(slots=True, kw_only=True)
class KnowledgeSpace(AggregateRoot["KnowledgeSpace"]):
    """A named space. Its key is unique, and it exists before any record in it.

    Attributes:
        id: Space id.
        key: Unique key.
        name: Display name.
    """

    id: SpaceId
    key: Key
    name: str

    @classmethod
    def create(cls, *, id: SpaceId, key: Key, name: str, now: datetime) -> Self:
        """Create a space.

        Returns:
            The space with `KnowledgeSpaceCreated` pending.
        """
        if not name.strip():
            raise InvalidRecordError("A space needs a name.", {"key": key.value})
        space: Self = cls(id=id, key=key, name=name.strip(), created_at=now, updated_at=now)
        space._record(KnowledgeSpaceCreated(aggregate_id=id.value, key=key))
        return space
