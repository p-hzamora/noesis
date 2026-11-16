"""Curator port: the judgment step, implemented by an LLM adapter."""

import abc
from collections.abc import Sequence

from noesis.bounded_context.knowledge.application.dtos import RelatedRecordDto
from noesis.bounded_context.knowledge.domain.value_objects import (
    CurationCandidate,
    CurationSubtypes,
    WorkBrief,
)


class ICurator(abc.ABC):
    """Judges a work brief and proposes candidates. Never writes the store."""

    @abc.abstractmethod
    async def judge(
        self, brief: WorkBrief, related: Sequence[RelatedRecordDto], subtypes: CurationSubtypes
    ) -> tuple[CurationCandidate, ...]:
        """Decide what in `brief` is worth keeping.

        Args:
            brief: The finished work (redacted).
            related: Existing records on similar topics, so it can refine instead of duplicate.
            subtypes: The subtypes it may choose from.

        Returns:
            The candidates, in order; an empty tuple is a valid answer. The admission policy,
            not the curator, decides the planned writes.

        Raises:
            CuratorRunFailedError: The run failed or its answer was unusable.
        """
        ...
