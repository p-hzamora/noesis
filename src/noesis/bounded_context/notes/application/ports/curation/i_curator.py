"""Curator port: the judgment step, implemented by an LLM adapter."""

import abc
from collections.abc import Sequence

from noesis.bounded_context.notes.application.dtos import NoteSummaryDto
from noesis.bounded_context.notes.application.services.manifest import KindCatalog
from noesis.bounded_context.notes.domain.value_objects import CurationDecision, WorkBrief


class ICurator(abc.ABC):
    """Judges a work brief against the admission rule and drafts note decisions. Never writes storage."""

    @abc.abstractmethod
    async def judge(
        self, brief: WorkBrief, related: Sequence[NoteSummaryDto], catalog: KindCatalog
    ) -> tuple[CurationDecision, ...]:
        """Decide what in `brief` is worth keeping.

        Args:
            brief: The finished work.
            related: Existing notes on similar topics, so it can update instead of duplicate.
            catalog: The kinds it may choose from, with their descriptions and sections.

        Returns:
            One decision per candidate; an empty tuple is a valid answer.

        Raises:
            CuratorFailedError: The run failed or its answer was unusable.
        """
        ...
