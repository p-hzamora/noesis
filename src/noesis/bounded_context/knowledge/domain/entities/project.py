"""The Project aggregate: the anchor of project scope, independent of records."""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from noesis.bounded_context.knowledge.domain.events import ProjectRegistered
from noesis.bounded_context.knowledge.domain.value_objects import Key, RecordId, SpaceId
from noesis.exceptions import InvalidRecordError
from noesis.shared_kernel.domain.entities import AggregateRoot


@dataclass(slots=True, kw_only=True)
class Project(AggregateRoot["Project"]):
    """A project inside a space; its key is unique within the space.

    Attributes:
        id: Record id.
        space_id: Owning space, fixed.
        key: Key unique within the space.
        name: Display name.
    """

    id: RecordId
    space_id: SpaceId
    key: Key
    name: str

    @classmethod
    def create(cls, *, id: RecordId, space_id: SpaceId, key: Key, name: str, now: datetime) -> Self:
        """Register a project.

        Returns:
            The project with `ProjectRegistered` pending.
        """
        if not name.strip():
            raise InvalidRecordError("A project needs a name.", {"key": key.value})
        project: Self = cls(
            id=id, space_id=space_id, key=key, name=name.strip(), created_at=now, updated_at=now
        )
        project._record(ProjectRegistered(aggregate_id=id.value, space_id=space_id.value, key=key))
        return project
