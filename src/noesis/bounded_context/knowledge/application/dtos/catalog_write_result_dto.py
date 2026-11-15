"""The outcome of `register` or `revise`."""

from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum
from noesis.shared_kernel.application.dtos import BaseDto


class CatalogWriteResultDto(BaseDto):
    """The outcome of `register` or `revise`.

    Attributes:
        id: The entry.
        kind: Entry kind.
        name: Entry name.
        revision: Revision written; the unchanged head number for a no-op revise.
        space_id: Space it lives in.
        replayed: True when the idempotency key was already used and nothing was written.
    """

    id: str
    kind: CatalogEntryKindEnum
    name: str
    revision: int
    space_id: str
    replayed: bool = False
