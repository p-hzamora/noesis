"""Atomically replace a source record's imported links."""

from noesis.bounded_context.knowledge.application.services.link_set_operation import (
    LinkSetOperation,
)
from noesis.bounded_context.knowledge.application.services.link_set_request import (
    LinkSetRequest,
    LinkSetResultDto,
)
from noesis.shared_kernel.application.handlers import IHandler


class ReplaceLinkSetHandler(LinkSetOperation, IHandler[LinkSetRequest, LinkSetResultDto]):
    """Command side of the link-set unit of work."""

    async def handle(self, action: LinkSetRequest) -> LinkSetResultDto:
        """Replace directly; identical content returns unchanged without ledger access."""
        return await self.execute(action, apply=True)
