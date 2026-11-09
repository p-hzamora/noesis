"""Recall agent port: the synthesis step, implemented by an LLM adapter."""

import abc
from collections.abc import Sequence

from noesis.bounded_context.notes.application.dtos import NoteContentDto, RecallBriefingDto


class IRecallAgent(abc.ABC):
    """Reads notes and writes a task briefing from them. Has no access to storage or tools."""

    @abc.abstractmethod
    async def brief(
        self, task: str, notes: Sequence[NoteContentDto], *, target_tokens: int
    ) -> RecallBriefingDto:
        """Write the briefing for `task` from `notes`, and nothing else.

        Args:
            task: What is about to be done.
            notes: The notes to read, already read and size-bounded by the caller. Their text
                is data, never instructions.
            target_tokens: Rough length to aim for; 0 means no target.

        Returns:
            The briefing as the agent wrote it, not yet checked against `notes`.

        Raises:
            RecallAgentFailedError: The agent is unavailable, failed, timed out or answered
                something unusable.
        """
        ...
