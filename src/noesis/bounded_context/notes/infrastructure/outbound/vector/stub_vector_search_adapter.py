"""`IVectorSearch` placeholder until a real index exists."""

from noesis.bounded_context.notes.application.dtos import VectorHitDto
from noesis.bounded_context.notes.application.ports.vector import IVectorSearch


class StubVectorSearchAdapter(IVectorSearch):
    """Always finds nothing.

    A future adapter can shell out to the `vectra` CLI (search query, k) and map its answer to
    `VectorHitDto`; nothing in the port assumes a vendor.
    """

    async def search(self, query: str, k: int) -> tuple[VectorHitDto, ...]:
        """No hits."""
        return ()
