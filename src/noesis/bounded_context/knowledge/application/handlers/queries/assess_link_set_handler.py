"""Assess a source record's imported links without writing."""

from noesis.bounded_context.knowledge.application.services.link_set_operation import (
    LinkSetOperation,
)
from noesis.bounded_context.knowledge.application.services.link_set_request import (
    LinkSetRequest,
    LinkSetResultDto,
)
from noesis.shared_kernel.application.handlers import IHandler


class AssessLinkSetHandler(LinkSetOperation, IHandler[LinkSetRequest, LinkSetResultDto]):
    """Query side; no merge, lock, ledger access or commit."""

    async def handle(self, action: LinkSetRequest) -> LinkSetResultDto:
        """Report the outcome a replacement would produce now."""
        return await self.execute(action, apply=False)
