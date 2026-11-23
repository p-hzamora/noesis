"""What interop needs from Knowledge, typed with the kernel contracts only.

An abstract interface in the kernel: the Knowledge inbound adapter inherits it and interop
never imports Knowledge.
"""

import abc

from noesis.shared_kernel.contracts.knowledge import (
    ImportKnowledgeOutcomeContract,
    ImportKnowledgeRequestContract,
)
from noesis.shared_kernel.contracts.knowledge.import_link_set_contract import (
    ImportLinkSetOutcomeContract,
    ImportLinkSetRequestContract,
)


class IKnowledgeImporter(abc.ABC):
    """Asks Knowledge what to do with a note, and does it."""

    @abc.abstractmethod
    async def assess(
        self, request: ImportKnowledgeRequestContract
    ) -> ImportKnowledgeOutcomeContract:
        """What `apply` would do now; writes nothing."""
        ...

    @abc.abstractmethod
    async def apply(
        self, request: ImportKnowledgeRequestContract
    ) -> ImportKnowledgeOutcomeContract:
        """Do it."""
        ...

    @abc.abstractmethod
    async def assess_links(
        self, request: ImportLinkSetRequestContract
    ) -> ImportLinkSetOutcomeContract:
        """Predict a link-set replacement without writing."""
        ...

    @abc.abstractmethod
    async def replace_links(
        self, request: ImportLinkSetRequestContract
    ) -> ImportLinkSetOutcomeContract:
        """Atomically replace one source's outgoing link set."""
        ...
