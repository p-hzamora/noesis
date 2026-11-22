"""Read a scoped, revision-checked briefing without changing Knowledge or projections."""

from ...dtos.briefing_dtos import RecallRequestDto, RecallResultDto
from ...services.task_briefing_service import TaskBriefingService


class RecallHandler(TaskBriefingService):
    """Recall is the task briefing pipeline behind the query-handler entry point.

    Subclassing keeps the constructor and collaborators of the pipeline unchanged for the
    composition root and existing tests; the logic lives only in `TaskBriefingService`.
    """

    async def handle(self, request: RecallRequestDto) -> RecallResultDto:
        """Gather evidence; typed store errors always propagate before synthesis."""
        return await self.brief(request)
