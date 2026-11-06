"""Show the journal of a capture session."""

from pydantic import Field

from noesis.bounded_context.capture.application.dtos import CaptureRunDto, CaptureRunListDto
from noesis.bounded_context.capture.application.ports.journal import ICaptureJournal
from noesis.bounded_context.capture.application.ports.read_repositories import (
    ICaptureSessionTreeReader,
)
from noesis.bounded_context.capture.domain.value_objects import SessionId
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject

MAX_CHILD_DEPTH: int = 8
"""Levels of sub-agents followed; a guard against a malformed (cyclic) tree."""


class ListCaptureRunsQuery(FrozenObject):
    """Journal of one session.

    Attributes:
        session_id: The agent session.
        limit: Most recent entries to return.
        include_children: Also merge the journals of the sub-agent sessions started from it.
    """

    session_id: str
    limit: int = Field(default=50, ge=1, le=1000)
    include_children: bool = False


class ListCaptureRunsHandler(IHandler[ListCaptureRunsQuery, CaptureRunListDto]):
    """Reads the session journal, newest `limit` entries in chronological order."""

    def __init__(self, *, journal: ICaptureJournal, tree: ICaptureSessionTreeReader) -> None:
        self._journal: ICaptureJournal = journal
        self._tree: ICaptureSessionTreeReader = tree

    async def handle(self, action: ListCaptureRunsQuery) -> CaptureRunListDto:
        """The journal entries (merged with the children's when asked, oldest first)."""
        session_id = SessionId(value=action.session_id)
        children: list[SessionId] = (
            await self._descendants(session_id) if action.include_children else []
        )
        runs: list[CaptureRunDto] = []
        for member in (session_id, *children):
            runs += [
                run.model_copy(update={"session_id": member.value})
                for run in await self._journal.read(member)
            ]
        runs.sort(key=lambda run: run.at)  # stable: same-second entries keep journal order
        return CaptureRunListDto(
            session_id=session_id.value,
            runs=tuple(runs[-action.limit :]),
            children=tuple(child.value for child in children),
        )

    async def _descendants(self, root: SessionId) -> list[SessionId]:
        """Breadth-first, each session once, no deeper than `MAX_CHILD_DEPTH`."""
        visited: set[str] = {root.value}
        found: list[SessionId] = []
        level: list[SessionId] = [root]
        for _ in range(MAX_CHILD_DEPTH):
            next_level: list[SessionId] = []
            for parent in level:
                for child in await self._tree.children_of(parent):
                    if child.value not in visited:
                        visited.add(child.value)
                        next_level.append(child)
            found += next_level
            level = next_level
            if not level:
                break
        return found
