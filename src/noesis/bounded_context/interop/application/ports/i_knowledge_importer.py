"""What interop needs from Knowledge, typed with the kernel contracts only.

A `typing.Protocol`, so the Knowledge inbound adapter satisfies it structurally and interop
never imports Knowledge.
"""

from typing import Protocol

from noesis.shared_kernel.contracts.knowledge import (
    ImportKnowledgeOutcomeContract,
    ImportKnowledgeRequestContract,
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
