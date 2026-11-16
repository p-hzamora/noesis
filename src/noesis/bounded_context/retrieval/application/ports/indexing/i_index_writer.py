"""A projection: a disposable copy of record text that can answer queries."""

import abc

from noesis.shared_kernel.contracts.knowledge import IndexableRecordContract
from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject

from ....domain.value_objects import ProjectionKey


class ProjectionEntryDto(FrozenObject):
    """One entry to write.

    Attributes:
        key: The record at its head revision.
        space_id: The space of the record.
        record: The record's text and metadata at that revision.
    """

    key: ProjectionKey
    space_id: str
    record: IndexableRecordContract


class IIndexWriter(abc.ABC):
    """Writes one projection; `kind` is its name and the `projection` of its cursor."""

    @property
    @abc.abstractmethod
    def kind(self) -> str:
        """Unique name of the projection."""
        ...

    @abc.abstractmethod
    async def upsert(self, entry: ProjectionEntryDto) -> None:
        """Write the entry, replacing the record's entry at any other revision."""
        ...

    @abc.abstractmethod
    async def clear(self, space_id: str) -> None:
        """Drop every entry of the space."""
        ...

    @abc.abstractmethod
    def profile(self) -> dict[str, JsonValue]:
        """What the projection was built with."""
        ...

    @abc.abstractmethod
    async def entries(self, space_id: str) -> dict[str, int | None]:
        """Record id to the revision held, for comparing with the records (`--verify`)."""
        ...
