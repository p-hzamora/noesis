"""An entry with no installed match."""

from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum
from noesis.shared_kernel.application.dtos import BaseDto


class NotInstalledDto(BaseDto):
    """An entry with no installed match.

    Attributes:
        entry_id: The entry.
        kind: Entry kind.
        name: Entry name.
        location: Where its definition lives (the install hint).
    """

    entry_id: str
    kind: CatalogEntryKindEnum
    name: str
    location: str
