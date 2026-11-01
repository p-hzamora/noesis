"""Curator port: the judgment step, implemented by an LLM adapter."""

import abc
from collections.abc import Sequence

from noesis.bounded_context.knowledge.application.dtos import NoteSummaryDto
from noesis.bounded_context.knowledge.domain.value_objects import CurationDecision
from noesis.shared_kernel.contracts import WorkBriefContract


class ICurator(abc.ABC):
    """Judges a work brief against the admission rule and drafts note decisions. Never writes storage."""

    @abc.abstractmethod
    async def curate(
        self, brief: WorkBriefContract, related: Sequence[NoteSummaryDto]
    ) -> tuple[CurationDecision, ...]:
        """Decide what in `brief` is worth keeping.

        Args:
            brief: The finished work.
            related: Existing notes on similar topics, so it can update instead of duplicate.

        Returns:
            One decision per candidate; an empty tuple is a valid answer.

        Raises:
            CuratorFailedError: The run failed or its answer was unusable.
        """
        ...
