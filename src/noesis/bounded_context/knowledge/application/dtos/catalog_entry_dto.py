"""A catalog entry with its head revision's content."""

from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum
from noesis.shared_kernel.application.dtos import BaseDto


class CatalogEntryDto(BaseDto):
    """A catalog entry with its head revision's content.

    Attributes:
        id: Entry id.
        space_id: Owning space.
        kind: Entry kind.
        name: Entry name.
        head_revision: Number of the head revision.
        purpose: What it is for.
        declared_version: Declared version, when there is one.
        prerequisites: What must be present, as `kind:name` text.
        location: Where its definition lives.
    """

    id: str
    space_id: str
    kind: CatalogEntryKindEnum
    name: str
    head_revision: int
    purpose: str
    declared_version: str | None = None
    prerequisites: tuple[str, ...] = ()
    location: str
