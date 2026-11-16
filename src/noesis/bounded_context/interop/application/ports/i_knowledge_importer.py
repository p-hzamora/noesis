"""What interop needs from Knowledge, typed with the kernel contracts only.

A `typing.Protocol`, so the Knowledge inbound adapter satisfies it structurally and interop
never imports Knowledge.
"""

from typing import Protocol

from noesis.shared_kernel.contracts.knowledge import (
    ImportKnowledgeOutcomeContract,
    ImportKnowledgeRequestContract,
)
from noesis.shared_kernel.contracts.knowledge.import_link_set_contract import (
    ImportLinkSetOutcomeContract,
    ImportLinkSetRequestContract,
)


class IKnowledgeImporter(Protocol):
    """Asks Knowledge what to do with a note, and does it."""

    async def assess(
        self, request: ImportKnowledgeRequestContract
    ) -> ImportKnowledgeOutcomeContract:
        """What `apply` would do now; writes nothing."""
        ...

    async def apply(
        self, request: ImportKnowledgeRequestContract
    ) -> ImportKnowledgeOutcomeContract:
        """Do it."""
        ...

    async def assess_links(
        self, request: ImportLinkSetRequestContract
    ) -> ImportLinkSetOutcomeContract:
        """Predict a link-set replacement without writing."""
        ...

    async def replace_links(
        self, request: ImportLinkSetRequestContract
    ) -> ImportLinkSetOutcomeContract:
        """Atomically replace one source's outgoing link set."""
        ...
